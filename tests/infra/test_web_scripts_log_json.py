"""The web container's shell scripts print JSON lines like the app (WP-2g), so
`docker compose logs --no-log-prefix web | jq` parses."""

import json
import re
import subprocess
from datetime import datetime

import pytest
from test_run_web_gunicorn import REPO, pytestmark, run  # noqa: F401

SCRIPTS = [
    'docker/entrypoint_web.sh',
    'docker/web/scripts/initialize_new_container.sh',
    'docker/web/scripts/run_web_gunicorn.sh',
]


@pytest.mark.parametrize('script', SCRIPTS)
def test_scripts_print_no_plain_text(script):
    plain = [
        line
        for line in (REPO / script).read_text().splitlines()
        if re.match(r'\s*echo\b', line)
    ]
    assert not plain


@pytest.mark.parametrize('script', SCRIPTS)
def test_log_json_writes_one_json_line(script):
    path = REPO / script
    define = re.search(r'^log_json\(\) \{.*?^\}$', path.read_text(), re.M | re.S)
    assert define is not None, f'{script} defines no log_json'
    result = subprocess.run(
        ['bash', '-c', f'{define.group(0)}\nlog_json "Running server..."', script],
        capture_output=True,
        text=True,
        check=True,
    )
    (line,) = result.stdout.splitlines()
    entry = json.loads(line)
    assert entry['level'] == 'INFO'
    assert entry['logger'] == path.name
    assert entry['message'] == 'Running server...'
    assert datetime.fromisoformat(entry['timestamp']).utcoffset().total_seconds() == 0


def test_run_web_gunicorn_status_lines_are_json(tmp_path):
    result = run(tmp_path, 'exit 0')
    lines = result.stdout.splitlines()
    assert lines
    messages = [json.loads(line)['message'] for line in lines]
    assert messages[-1] == 'Master gunicorn process has ended.'
