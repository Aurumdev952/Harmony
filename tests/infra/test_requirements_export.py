import re
import shutil
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docker"))

import export_requirements  # noqa: E402

# Requirements that were not ==-pinned when pyproject.toml took over from the
# requirements files (WP-2f). Every other line must be ==-pinned or a git source
# (SEC-9). Tightening one of these to == means deleting it here.
UNPINNED_AT_ADOPTION = {
    "Cython<3.0.0",
    "importlib_metadata<5",
    "hvac>=0.7.0",
    "pandas>=1.3,<2.0",
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
    "dataclasses",
    "pytest>=7.4.3",
    "pytest-flask>=0.15.0",
    "pytest-xdist>=1.29.0",
    "pytest-metadata>=1.8.0",
    "junit-xml>=1.9",
    "PyInstaller>=3.4",
}


def write_pyproject(tmp_path: Path, text: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(text)
    return tmp_path


def test_new_requirements_are_pinned_exactly():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    sources = {
        export_requirements.normalise(name)
        for name in pyproject["tool"]["uv"]["sources"]
    }
    lists = [
        pyproject["project"]["dependencies"],
        *pyproject["dependency-groups"].values(),
    ]
    loose = []
    for requirement in (r for group in lists for r in group):
        spec = requirement.split(";")[0].strip()
        name = re.match(r"[A-Za-z0-9._-]+", spec).group(0)
        if "==" in spec or export_requirements.normalise(name) in sources:
            continue
        if spec not in UNPINNED_AT_ADOPTION:
            loose.append(spec)
    assert loose == []


SOURCES_TEMPLATE = """
[project]
name = "x"
version = "0"
dependencies = [{dependency!r}]

[dependency-groups]
web = []
pipeline = []
dev = []

[tool.uv.sources]
{source} = {{ git = "https://example.invalid/x.git", rev = "{rev}" }}
"""
SHA = "bd398c18e8710a4e7cc87d9abb6ba9a95e7ba792"


def test_source_names_match_after_normalisation(tmp_path):
    root = write_pyproject(
        tmp_path,
        SOURCES_TEMPLATE.format(
            dependency="flask_potion", source="Flask-Potion", rev=SHA
        ),
    )
    base = export_requirements.expected_files(root)[root / "requirements.txt"]

    assert (
        f"-e git+https://example.invalid/x.git@{SHA}#egg=flask_potion"
        in base.splitlines()
    )


def test_unused_source_is_an_error(tmp_path, capsys):
    root = write_pyproject(
        tmp_path,
        SOURCES_TEMPLATE.format(dependency="requests==2.28.1", source="pylib", rev=SHA),
    )

    assert export_requirements.main(["--check"], root=root) == 2
    assert "pylib" in capsys.readouterr().err


@pytest.mark.parametrize("rev", ["main", "v1.0", SHA[:12], SHA.upper()])
def test_source_rev_must_be_a_full_commit_sha(tmp_path, capsys, rev):
    root = write_pyproject(
        tmp_path, SOURCES_TEMPLATE.format(dependency="pylib", source="pylib", rev=rev)
    )

    assert export_requirements.main(["--check"], root=root) == 2
    assert "40-character" in capsys.readouterr().err


def test_committed_requirements_match_pyproject():
    assert export_requirements.main(["--check"]) == 0


def copy_inputs(tmp_path: Path) -> Path:
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    export_requirements.main([], root=tmp_path)
    return tmp_path


def test_check_fails_on_a_hand_edited_file_and_leaves_it(tmp_path, capsys):
    root = copy_inputs(tmp_path)
    edited = root / "requirements-web.txt"
    edited.write_text(edited.read_text() + "requests==2.32.0\n")

    assert export_requirements.main(["--check"], root=root) == 1
    assert "requirements-web.txt" in capsys.readouterr().err
    assert edited.read_text().endswith("requests==2.32.0\n")


def test_write_restores_a_stale_file(tmp_path):
    root = copy_inputs(tmp_path)
    (root / "requirements.txt").unlink()

    assert export_requirements.main([], root=root) == 0
    assert export_requirements.main(["--check"], root=root) == 0


def test_git_sources_become_editable_vcs_lines():
    files = export_requirements.expected_files(ROOT)
    base = files[ROOT / "requirements.txt"].splitlines()

    assert (
        "-e git+https://github.com/Zenysis/potion.git"
        "@bd398c18e8710a4e7cc87d9abb6ba9a95e7ba792#egg=Flask-Potion"
    ) in base
    assert "Flask-Potion" not in base
