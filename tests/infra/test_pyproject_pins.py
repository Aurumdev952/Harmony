"""pyproject.toml pins every dependency (SEC-9), and the pins work together."""

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text())

# Requirements that were not ==-pinned when pyproject.toml took over from the
# requirements files (WP-2f). Every other one must be ==-pinned or a git source
# pinned to a full commit SHA. Tightening one of these to == means deleting it
# here (test_unpinned_allowance_has_no_stale_entries).
UNPINNED_AT_ADOPTION = {
    "Cython<3.0.0",
    "importlib_metadata<5",
    "hvac>=0.7.0",
    "python-dateutil>=2.8.1",
    "six>=1.9.0",
    "python-slugify",
    "retry>=0.9.2",
    "watchdog>=0.8.3",
    "pyyaml>=3.12",
    "related>=0.7.0",
    "gspread>=5.4.0",
    "openpyxl>=3.0.9",
    "isodate>=0.5.4",
    "scipy>=1.2.1",
    "alembic>=1.7.1",
    "xlrd>=1.0.0",
    "pyshp",
    "contextlib2",
    "lxml",
    "oauthlib",
    "requests_oauthlib",
    "isoweek",
    "scikit-learn>=0.21.3",
    "netCDF4",
    "pytest>=7.4.3",
    "pytest-flask>=0.15.0",
    "pytest-xdist>=1.29.0",
    "pytest-metadata>=1.8.0",
    "junit-xml>=1.9",
    "PyInstaller>=3.4",
}


def normalise(name: str) -> str:
    """PEP 503 name normalisation, as uv applies it to [tool.uv.sources] keys."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirements() -> list[str]:
    groups = [
        PYPROJECT["project"]["dependencies"],
        *PYPROJECT["dependency-groups"].values(),
    ]
    return [r.split(";")[0].strip() for group in groups for r in group]


def name_of(spec: str) -> str:
    return normalise(re.match(r"[A-Za-z0-9._-]+", spec).group(0))


def test_new_requirements_are_pinned_exactly():
    sources = {normalise(name) for name in PYPROJECT["tool"]["uv"]["sources"]}
    loose = [
        spec
        for spec in requirements()
        if "==" not in spec
        and name_of(spec) not in sources
        and spec not in UNPINNED_AT_ADOPTION
    ]
    assert loose == []


def test_unpinned_allowance_has_no_stale_entries():
    assert UNPINNED_AT_ADOPTION <= set(requirements())


def test_git_sources_are_pinned_to_full_commit_shas():
    for name, source in PYPROJECT["tool"]["uv"]["sources"].items():
        assert re.fullmatch(r"[0-9a-f]{40}", source.get("rev", "")), name


def test_passlib_can_hash_with_the_locked_bcrypt():
    # scripts/create_user.py and Flask-User hash through passlib 1.7.4, which
    # raises on bcrypt >= 5.0 (4.1 to 4.3 only log a version warning).
    assert "bcrypt==4.0.1" in requirements()
    from passlib.context import CryptContext

    context = CryptContext(schemes=["bcrypt"])
    assert context.verify("password", context.hash("password"))


def test_the_locked_environment_satisfies_every_installed_requirement(tmp_path):
    # The images install groups of this lock, so a requirement no installed
    # version satisfies (a backport for an older Python, a too-low floor) shows
    # here first. Run outside the repo so uv reads no project settings.
    uv = shutil.which("uv")
    assert uv, "uv is on PATH wherever this suite runs (CI: setup-uv)"
    result = subprocess.run(
        [uv, "pip", "check", "--python", sys.executable],
        capture_output=True, text=True, cwd=tmp_path, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr
