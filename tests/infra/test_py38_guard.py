"""CI's Python 3.8 syntax guard covers everything the 3.8 web image can import.

The web image runs CPython 3.8 until WP-3b, but the CI job runs 3.9, which accepts
3.9-only syntax. The guard step parses the listed directories with a real 3.8, so a
directory missing from its list can break the image with every check green. WP-3b
deletes the step, and this test, when the image moves to 3.13.
"""

import re
import shlex
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEB_IMAGES = ["docker/web/Dockerfile_web-server", "docker/web/Dockerfile_web"]
# Suites that build the web app or import its packages (lead decision for WP-3b,
# 2026-10-06: the guard checks everything the 3.8 image can import).
TEST_DIRS = {
    "tests/web",
    "tests/authz",
    "tests/privilege_escalation",
    "tests/db",
    "tests/contract",
    "tests/infra",
    "tests/core",
}


def guard_dirs() -> set[str]:
    workflow = (REPO / ".github/workflows/integration.yml").read_text()
    (command,) = [
        line.split("run:", 1)[1]
        for line in workflow.splitlines()
        if "run:" in line and "ci/check_py38_syntax.py" in line
    ]
    words = shlex.split(command)
    return set(words[words.index("ci/check_py38_syntax.py") + 1 :])


def copied_python_files(dockerfile: str) -> set[Path]:
    files = set()
    for line in (REPO / dockerfile).read_text().splitlines():
        match = re.match(r"COPY\s+(.+)$", line.strip())
        if not match or "--from" in match.group(1):
            continue
        sources = [w for w in match.group(1).split() if not w.startswith("--")][:-1]
        for source in sources:
            for path in REPO.glob(source):
                found = path.rglob("*.py") if path.is_dir() else [path]
                files.update(f for f in found if f.suffix == ".py")
    return files


def test_the_guard_covers_every_python_file_the_web_images_copy():
    guarded = [REPO / d for d in guard_dirs()]
    for dockerfile in WEB_IMAGES:
        files = copied_python_files(dockerfile)
        assert files, dockerfile
        missing = {
            str(f.relative_to(REPO))
            for f in files
            if not any(f.is_relative_to(d) for d in guarded)
        }
        assert missing == set(), f"{dockerfile} copies unguarded {sorted(missing)}"


def test_the_guard_covers_the_suites_that_import_the_web_app():
    assert TEST_DIRS - guard_dirs() == set()


def test_every_guarded_directory_exists():
    assert [d for d in sorted(guard_dirs()) if not (REPO / d).is_dir()] == []
