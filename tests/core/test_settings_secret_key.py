"""SEC-3: no process starts with an empty or default DEFAULT_SECRET_KEY.

Run with: uv run --no-project --with pytest pytest tests/core
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _import_settings(secret_key: str | None) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ('DEFAULT_SECRET_KEY', 'PYTHONPATH')
    }
    env['DRUID_HOST'] = 'http://druid.invalid'
    if secret_key is not None:
        env['DEFAULT_SECRET_KEY'] = secret_key
    return subprocess.run(
        [
            sys.executable,
            '-c',
            'from config import settings; print(repr(settings.DEFAULT_SECRET_KEY))',
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    'secret_key',
    [None, '', '   ', 'changeme', 'CHANGEME', ' ChangeMe\n'],
    ids=['unset', 'empty', 'blank', 'changeme', 'upper', 'padded'],
)
def test_refuses_to_start_without_a_real_key(secret_key):
    result = _import_settings(secret_key)

    assert result.returncode != 0
    assert 'RuntimeError' in result.stderr
    assert 'DEFAULT_SECRET_KEY' in result.stderr
    assert 'openssl rand -hex 32' in result.stderr


def test_accepts_a_real_key_unchanged():
    key = ' 9f2c4e6a8b0d1f3e5a7c9b1d3f5e7a9c '

    result = _import_settings(key)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == repr(key)
