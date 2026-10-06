"""The contract stack tags its web image by exactly what the image installs from.

The hash inputs are the web-server Dockerfile and every file its build binds in
(``--mount=type=bind,source=...``). A missing input must stop ``stack.sh``, and
an edit to any input must change the tag, so a stale image is never reused.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STACK_SCRIPT = ROOT / "tests" / "contract" / "stack" / "stack.sh"
DOCKERFILE = Path("docker/web/Dockerfile_web-server")
TAG = re.compile(r"harmony-contract-web-server:[0-9a-f]{12}")


def hash_inputs() -> list[Path]:
    text = (ROOT / DOCKERFILE).read_text()
    bound = re.findall(r"--mount=type=bind,source=([^,\s]+)", text)
    return [DOCKERFILE, *(Path(source) for source in bound)]


def image_tag(root: Path) -> subprocess.CompletedProcess:
    script = root / "tests" / "contract" / "stack" / "stack.sh"
    return subprocess.run(
        ["bash", str(script), "image-tag"], capture_output=True, text=True, check=False
    )


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A checkout holding only stack.sh and the hash inputs."""
    stack = tmp_path / "tests" / "contract" / "stack"
    stack.mkdir(parents=True)
    shutil.copy2(STACK_SCRIPT, stack / "stack.sh")
    for relative in hash_inputs():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return tmp_path


def test_the_dockerfile_binds_the_uv_project_files():
    assert set(hash_inputs()) >= {DOCKERFILE, Path("pyproject.toml"), Path("uv.lock")}


def test_image_tag_works_on_this_checkout():
    done = image_tag(ROOT)
    assert done.returncode == 0, done.stderr
    assert TAG.fullmatch(done.stdout.strip())


def test_image_tag_needs_nothing_but_the_hash_inputs(sandbox):
    done = image_tag(sandbox)
    assert done.returncode == 0, done.stderr
    assert done.stdout == image_tag(ROOT).stdout


@pytest.mark.parametrize("relative", hash_inputs(), ids=str)
def test_editing_a_hash_input_changes_the_tag(sandbox, relative):
    before = image_tag(sandbox).stdout
    with (sandbox / relative).open("a") as handle:
        handle.write("\n# edited\n")
    after = image_tag(sandbox)
    assert after.returncode == 0, after.stderr
    assert after.stdout != before


@pytest.mark.parametrize("relative", hash_inputs(), ids=str)
def test_a_missing_hash_input_stops_the_script(sandbox, relative):
    (sandbox / relative).unlink()
    done = image_tag(sandbox)
    assert done.returncode != 0
    assert not TAG.search(done.stdout)


def build_calls(tmp_path: Path, **env: str) -> list[str]:
    """Run `stack.sh up` with a fake docker that records each call, builds
    successfully and fails at the first `compose`, so `up` stops right after
    building; return the recorded `docker build` argument lines."""
    calls = tmp_path / "docker-calls"
    fake = tmp_path / "bin" / "docker"
    fake.parent.mkdir(parents=True)
    fake.write_text(
        f"#!/bin/bash\necho \"$*\" >> {calls}\n[[ $1 == build ]] && exit 0\nexit 1\n"
    )
    fake.chmod(0o755)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    done = subprocess.run(
        ["bash", str(STACK_SCRIPT), "up"],
        env={
            "PATH": f"{fake.parent}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "XDG_RUNTIME_DIR": str(runtime),
            "CONTRACT_PROJECT": "contract-build-test",
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode != 0
    lines = calls.read_text().splitlines()
    assert any(line.startswith("compose ") for line in lines), done.stderr
    return [line for line in lines if line.startswith("build ")]


def test_the_web_image_builds_on_the_default_network_by_default(tmp_path):
    (build,) = build_calls(tmp_path)
    assert "--network" not in build.split()


def test_contract_build_network_reaches_the_web_image_build(tmp_path):
    (build,) = build_calls(tmp_path, CONTRACT_BUILD_NETWORK="host")
    words = build.split()
    assert words[words.index("--network") + 1] == "host"
