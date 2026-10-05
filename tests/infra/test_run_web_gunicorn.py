"""docker/web/scripts/run_web_gunicorn.sh exits non-zero when gunicorn refuses to start."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'docker/web/scripts/run_web_gunicorn.sh'

pytestmark = pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')


def run(tmp_path, server_body, sleep_body='exit 0'):
    pid_file = tmp_path / 'gunicorn_master.pid'
    server = tmp_path / 'web/gunicorn_server.py'
    server.parent.mkdir()
    server.write_text(f'#!/bin/bash\n{server_body}\n')
    server.chmod(0o755)
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    sleep = bin_dir / 'sleep'
    sleep.write_text(f'#!/bin/bash\n{sleep_body}\n')
    sleep.chmod(0o755)
    return subprocess.run(
        ['bash', str(SCRIPT)],
        cwd=tmp_path,
        env={
            'PATH': f'{bin_dir}:/usr/bin:/bin',
            'GUNICORN_PID_FILE': str(pid_file),
            'PID_FILE_PATH': str(pid_file),
            'STATE': str(tmp_path / 'sleeps'),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_refused_start_exits_with_the_server_status(tmp_path):
    result = run(tmp_path, 'echo "RuntimeError: JWT_SECRET_KEY ..." >&2; exit 3')
    assert result.returncode == 3, result.stdout + result.stderr


def test_clean_shutdown_exits_zero(tmp_path):
    result = run(tmp_path, 'exit 0')
    assert result.returncode == 0, result.stdout + result.stderr


def test_replaced_master_keeps_watching_and_exits_zero(tmp_path):
    # The original master exits non-zero after a replacement master wrote the
    # PID file; the script must follow the replacement, not the old status.
    server = 'echo 4242 > "$PID_FILE_PATH"; exit 1'
    sleep = (
        'n=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$STATE"; '
        '[ "$n" -ge 2 ] && rm -f "$PID_FILE_PATH"; exit 0'
    )
    result = run(tmp_path, server, sleep)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Master gunicorn process has ended.' in result.stdout
