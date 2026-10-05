"""Every image runs the one CPython release the lock targets, installed with one uv."""

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCKERFILES = sorted((REPO / "docker").rglob("Dockerfile*"))
PYTHON_IMAGE = re.compile(r"python:(3\.\d+\.\d+)-slim-bookworm@sha256:[0-9a-f]{64}")
UV_IMAGE = re.compile(r"ghcr\.io/astral-sh/uv:([\d.]+)@sha256:[0-9a-f]{64}")


def text(path: Path) -> str:
    return path.read_text()


def test_python_base_images_are_one_pinned_release():
    found = {m.group(0) for p in DOCKERFILES for m in PYTHON_IMAGE.finditer(text(p))}
    assert len(found) == 1, found
    (image,) = found
    version = PYTHON_IMAGE.match(image).group(1)
    requires = tomllib.loads(text(REPO / "pyproject.toml"))["project"][
        "requires-python"
    ]
    assert requires == "==" + ".".join(version.split(".")[:2]) + ".*"
    # The dev image is Ubuntu-based and installs the same release through uv.
    assert f"uv python install {version}" in text(REPO / "docker/dev/Dockerfile")


def test_images_copy_one_uv_release():
    found = {m.group(0) for p in DOCKERFILES for m in UV_IMAGE.finditer(text(p))}
    assert len(found) == 1, found


def test_no_image_or_compose_file_installs_pypy_or_pip_requirements():
    files = [*DOCKERFILES, *REPO.glob("docker-compose*.yaml")]
    for path in files:
        lines = text(path).lower().splitlines()
        body = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
        assert "pypy" not in body, path
        assert "pip install" not in body, path
