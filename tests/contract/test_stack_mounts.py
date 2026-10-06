"""Where the contract stack (and the e2e stack built on it) mounts the checkout.

The web image keeps its Python environment in a venv under /zenysis (WP-3b), so
no service that runs the image may mount anything over it. The checkout is
mounted read-only, so the upload folder the app writes to must be a writable
mount of its own, whose mount point `stack.sh up` creates in the checkout.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[2]
STACK_SCRIPT = ROOT / "tests" / "contract" / "stack" / "stack.sh"
E2E_OVERLAY = ROOT / "e2e" / "stack" / "compose.e2e.yaml"
WEB_IMAGE = "contract-web-image-under-test"
OVERLAYS = {"contract": "", "e2e": str(E2E_OVERLAY)}


def image_venv() -> PurePosixPath:
    dockerfile = (ROOT / "docker/web/Dockerfile_web-server").read_text()
    (venv,) = re.findall(r"UV_PROJECT_ENVIRONMENT=(\S+)", dockerfile)
    return PurePosixPath(venv)


def upload_folder() -> str:
    """DATA_UPLOAD_FOLDER, which the app resolves against its working directory."""
    flask = (ROOT / "web/server/configuration/flask.py").read_text()
    (folder,) = re.findall(r"^DATA_UPLOAD_FOLDER = '([^']+)'$", flask, re.MULTILINE)
    return folder


def render(tmp_path: Path, overlays: str) -> dict:
    done = subprocess.run(
        ["bash", str(STACK_SCRIPT), "config", "--format", "json"],
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(tmp_path),
            "XDG_RUNTIME_DIR": str(tmp_path),
            "CONTRACT_WEB_IMAGE": WEB_IMAGE,
            "CONTRACT_OVERLAYS": overlays,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["services"]


def web_image_services(services: dict) -> dict:
    return {n: s for n, s in services.items() if s.get("image") == WEB_IMAGE}


@pytest.mark.parametrize("stack", OVERLAYS)
def test_no_web_image_service_mounts_over_the_image_venv(tmp_path, stack):
    venv = image_venv()
    services = web_image_services(render(tmp_path, OVERLAYS[stack]))
    assert {"web", "web-init"} <= set(services)
    for name, service in services.items():
        for volume in service.get("volumes", []):
            target = PurePosixPath(volume["target"])
            assert not (target == venv or target in venv.parents), (name, volume)
        for mount in service.get("tmpfs", []):
            target = PurePosixPath(mount.split(":")[0])
            assert not (target == venv or target in venv.parents), (name, mount)


@pytest.mark.parametrize("stack", OVERLAYS)
def test_web_can_write_the_upload_folder(tmp_path, stack):
    # e2e's upload smoke failed with HTTP 500, `OSError: Read-only file
    # system: 'uploads/self_serve'`, once the checkout moved to a read-only /src.
    web = render(tmp_path, OVERLAYS[stack])["web"]
    folder = PurePosixPath(web["working_dir"]) / upload_folder()
    writable = [PurePosixPath(m.split(":")[0]) for m in web.get("tmpfs", [])]
    writable += [
        PurePosixPath(v["target"])
        for v in web.get("volumes", [])
        if not v.get("read_only", False)
    ]
    assert any(folder == w or w in folder.parents for w in writable), (
        folder,
        writable,
    )


def test_up_creates_the_upload_mount_point_before_compose(tmp_path):
    # Docker cannot create a mount point inside a read-only bind mount.
    root = tmp_path / "checkout"
    stack = root / "tests" / "contract" / "stack"
    stack.mkdir(parents=True)
    shutil.copy2(STACK_SCRIPT, stack / "stack.sh")
    for relative in (
        "docker/web/Dockerfile_web-server",
        "pyproject.toml",
        "uv.lock",
        "web/server/configuration/flask.py",
    ):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, root / relative)
    seen = tmp_path / "seen-at-compose"
    fake = tmp_path / "bin" / "docker"
    fake.parent.mkdir()
    fake.write_text(
        "#!/bin/bash\n"
        "[[ $1 == build ]] && exit 0\n"
        f"[[ $1 == compose ]] && ls -d {root}/uploads > {seen} 2>&1\n"
        "exit 1\n"
    )
    fake.chmod(0o755)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    done = subprocess.run(
        ["bash", str(stack / "stack.sh"), "up"],
        env={
            "PATH": f"{fake.parent}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "XDG_RUNTIME_DIR": str(runtime),
            "CONTRACT_PROJECT": "contract-mount-test",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert seen.exists(), done.stderr
    assert seen.read_text().strip() == f"{root}/uploads"
