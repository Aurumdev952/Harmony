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


def test_the_renderer_alone_targets_its_image_python():
    # Decision 0013: the renderer image runs the Playwright base's CPython 3.12,
    # so its code must not use 3.13-only syntax. No other path has its own target.
    pyproject = tomllib.loads((REPO / 'pyproject.toml').read_text())
    assert pyproject['tool']['ruff'].get('per-file-target-version') == {
        'harmony/worker/renderer/**': 'py312'
    }
    settings = ruff_settings('harmony/worker/renderer/server.py')
    assert 'harmony/worker/renderer/**' in settings
    assert '3.12' in settings.split('linter.per_file_target_version =')[1]
