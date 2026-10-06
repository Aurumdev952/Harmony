"""ci/check_py38_syntax.py fails on the 3.9+ with-statement forms the 3.8 image breaks on."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "check_py38_syntax.py"

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")


def check(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "module.py").write_text(source)
    return subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "-p",
            "cpython-3.8.20",
            "python",
            str(SCRIPT),
            "pkg",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_python_38_code_passes(tmp_path):
    result = check(tmp_path, "with open('a') as a, open('b') as b:\n    pass\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 files checked, 0 problems" in result.stdout


def test_parenthesised_with_fails(tmp_path):
    result = check(
        tmp_path, "with (\n    open('a') as a,\n    open('b') as b,\n):\n    pass\n"
    )
    assert result.returncode == 1
    assert "pkg/module.py:" in result.stdout
    assert "not valid Python 3.8" in result.stdout


def test_parenthesised_with_without_as_fails(tmp_path):
    # Python 3.8 parses this as one tuple context manager and fails only at run time.
    result = check(tmp_path, "with (open('a'), open('b')):\n    pass\n")
    assert result.returncode == 1
    assert "pkg/module.py:1: `with (a, b):` is a tuple on Python 3.8" in result.stdout
