"""ruff targets the one interpreter every image runs, from requires-python."""

import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def ruff_settings(path: str) -> str:
    return subprocess.run(
        [sys.executable, '-m', 'ruff', 'check', '--show-settings', path],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
    ).stdout


def test_ruff_target_follows_requires_python():
    pyproject = tomllib.loads((REPO / 'pyproject.toml').read_text())
    # "==3.13.*" -> "3.13"
    version = pyproject['project']['requires-python'].strip('=*').rstrip('.')
    for path in ['web/server/app.py', 'prod/browser_share/browser_share.py']:
        settings = ruff_settings(path)
        assert f'linter.unresolved_target_version = {version}\n' in settings
        assert f'formatter.unresolved_target_version = {version}\n' in settings
        assert 'linter.per_file_target_version = {}' in settings, settings
