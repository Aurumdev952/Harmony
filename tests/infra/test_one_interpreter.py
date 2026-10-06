"""Every image runs the one CPython release the lock targets, installed with one uv,
except the export renderer (decision 0013).

Each Dockerfile's final stage is followed back to the image it starts from: another
stage, one of our own images (built from another Dockerfile here), or a third-party
base whose interpreter is declared below. A base that is not declared fails the
test, so a new image cannot slip in another interpreter.
"""

import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCKERFILES = sorted(
    p for p in (REPO / "docker").rglob("Dockerfile*") if p.suffix != ".dockerignore"
)
PYTHON_IMAGE = re.compile(r"python:(3\.\d+\.\d+)-slim-bookworm@sha256:[0-9a-f]{64}")
UV_IMAGE = re.compile(r"ghcr\.io/astral-sh/uv:([\d.]+)@sha256:[0-9a-f]{64}")
FROM = re.compile(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", re.I | re.M)

# Our images, by the name their FROM lines use, and the Dockerfile that builds them.
OWN_IMAGES = {
    "${NAMESPACE}/${IMAGE_PREFIX}-web-server:${TAG}": "docker/web/Dockerfile_web-server",
    "${NAMESPACE}/${IMAGE_PREFIX}-web-client:${TAG}": "docker/web/Dockerfile_web-client",
    "${RENDERER_IMAGE}": "docker/renderer/Dockerfile",
}
# Third-party bases with no Python interpreter: the client image is a Node build.
NO_PYTHON = re.compile(r"node:\S+@sha256:[0-9a-f]{64}")
# Decision 0013: the renderer keeps the Playwright image's interpreter, which must
# match its browser build. WP-7g lifts this.
EXCEPTION_BASE = re.compile(
    r"mcr\.microsoft\.com/playwright/python:v[\d.]+-noble@sha256:[0-9a-f]{64}"
)
EXCEPTION_PYTHON = "3.12"
EXCEPTIONS = {"docker/renderer/Dockerfile", "docker/renderer/Dockerfile.test"}


def text(path: Path) -> str:
    return path.read_text()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO))


def lock_minor() -> str:
    requires = tomllib.loads(text(REPO / "pyproject.toml"))["project"][
        "requires-python"
    ]
    return requires.strip("=*").rstrip(".")


def interpreter(dockerfile: str) -> str | None:
    """The CPython release the image's final stage runs ("3.13.16", "3.12"), or None
    for an image with no Python."""
    body = text(REPO / dockerfile)
    stages = {name: image for image, name in FROM.findall(body) if name}
    image = FROM.findall(body)[-1][0]
    while image in stages:
        image = stages[image]
    if image in OWN_IMAGES:
        return interpreter(OWN_IMAGES[image])
    if match := PYTHON_IMAGE.fullmatch(image):
        return match.group(1)
    if EXCEPTION_BASE.fullmatch(image):
        return EXCEPTION_PYTHON
    if NO_PYTHON.fullmatch(image):
        return None
    if image.startswith("ubuntu:") and (
        installed := re.search(r"uv python install (3\.\d+\.\d+)", body)
    ):
        return installed.group(1)
    raise AssertionError(f"{dockerfile}: undeclared base image {image}")


@pytest.mark.parametrize("dockerfile", [rel(p) for p in DOCKERFILES])
def test_every_image_runs_the_lock_interpreter_or_is_the_renderer(dockerfile):
    version = interpreter(dockerfile)
    if dockerfile in EXCEPTIONS:
        assert version == EXCEPTION_PYTHON
    elif version is not None:
        assert version.startswith(lock_minor() + "."), (dockerfile, version)


def test_the_images_on_the_lock_interpreter_share_one_release():
    versions = {interpreter(rel(p)) for p in DOCKERFILES if rel(p) not in EXCEPTIONS}
    assert len(versions - {None}) == 1, versions


def test_the_exception_is_exactly_the_renderer():
    others = {rel(p) for p in DOCKERFILES} - EXCEPTIONS
    assert EXCEPTIONS <= {rel(p) for p in DOCKERFILES}
    assert all(interpreter(d) != EXCEPTION_PYTHON for d in others)


def test_images_copy_one_uv_release():
    found = {m.group(0) for p in DOCKERFILES for m in UV_IMAGE.finditer(text(p))}
    assert len(found) == 1, found


def code(path: Path) -> str:
    lines = text(path).lower().splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def test_no_image_or_compose_file_installs_pypy():
    for path in [*DOCKERFILES, *REPO.glob("docker-compose*.yaml")]:
        assert "pypy" not in code(path), path


def test_no_tooling_config_mentions_pypy():
    for name in ["pyproject.toml", ".dockerignore", ".gitignore"]:
        assert "pypy" not in code(REPO / name), name


def test_only_the_renderer_installs_with_pip_and_only_by_hash():
    for path in [*DOCKERFILES, *REPO.glob("docker-compose*.yaml")]:
        installs = re.findall(r"pip install[^\n]*", code(path))
        if rel(path) in EXCEPTIONS:
            assert installs, path
            assert all("--require-hashes" in i and "--no-deps" in i for i in installs)
        else:
            assert installs == [], path
