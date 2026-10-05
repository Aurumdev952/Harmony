'''Importing the web app writes only JSON lines: `log` is configured, and warnings are
captured into logging, before any third-party import can print a warning.
'''

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


@pytest.mark.parametrize('module', ['web.server.app', 'web.server.app_base'])
def test_importing_the_app_writes_only_json_lines(module: str, tmp_path: Path) -> None:
    pytest.importorskip('flask_migrate')
    env = {
        'PATH': os.environ['PATH'],
        'PYTHONPATH': REPO_ROOT,
        'ZEN_ENV': 'harmony_demo',
        'DRUID_HOST': 'http://druid.invalid',
        'DEFAULT_SECRET_KEY': 'tests-web-import-key-0123456789abcdef',
        'SQLALCHEMY_DATABASE_URI': 'postgresql://zen@db.invalid/zen',
        'LOG_FORMAT': 'json',
        'PYTHONWARNINGS': 'always',
        # A fresh bytecode cache, so modules are compiled again and compile-time
        # SyntaxWarnings (flask_potion's utils.py) are raised as in a new image.
        'PYTHONPYCACHEPREFIX': str(tmp_path / 'pycache'),
    }
    result = subprocess.run(
        [sys.executable, '-c', f'import {module}'],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = (result.stdout + result.stderr).splitlines()
    not_json = []
    for line in lines:
        try:
            json.loads(line)
        except ValueError:
            not_json.append(line)
    assert not_json == []
    assert any(json.loads(line)['logger'] == 'py.warnings' for line in lines)
