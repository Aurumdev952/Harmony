import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docker"))

import export_requirements  # noqa: E402


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


def test_markers_are_kept_verbatim():
    files = export_requirements.expected_files(ROOT)
    pipeline = files[ROOT / "requirements-pipeline.txt"].splitlines()

    assert "lxml ; platform_python_implementation != 'PyPy'" in pipeline
