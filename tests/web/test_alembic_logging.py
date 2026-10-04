from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _flask_db(
    command: list[str], database: Path, log_level: str
) -> subprocess.CompletedProcess[str]:
    env = {
        'PATH': os.environ['PATH'],
        'PYTHONPATH': REPO_ROOT,
        'FLASK_APP': 'web.server.app',
        'ZEN_ENV': 'harmony_demo',
        'ZEN_OFFLINE': '1',
        'DEFAULT_SECRET_KEY': 'tests-web-placeholder-key',
        'DRUID_HOST': 'http://druid.invalid',
        'DATABASE_URL': f'sqlite:///{database}',
        'LOG_FORMAT': 'json',
        'LOG_LEVEL': log_level,
    }
    return subprocess.run(
        [sys.executable, '-m', 'flask', 'db', *command],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize('log_level', ['WARNING', 'DEBUG'])
def test_migration_environment_logs_json_lines(tmp_path: Path, log_level: str) -> None:
    pytest.importorskip('flask_migrate')
    result = _flask_db(['stamp', 'head'], tmp_path / 'scratch.db', log_level)

    assert result.returncode == 0, result.stderr[-2000:]
    lines = result.stderr.splitlines()
    assert lines, 'flask db stamp wrote no log lines'
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pytest.fail(f'not a JSON log line: {line!r}')

    assert any(
        entry['logger'] == 'alembic.runtime.migration'
        and entry['message'] == 'Context impl SQLiteImpl.'
        for entry in entries
    ), 'alembic INFO lines are missing'
    assert not any(entry['logger'].startswith('sqlalchemy.engine') for entry in entries)
