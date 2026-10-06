"""The web container's shell scripts print JSON lines like the app (WP-2g), so
`docker compose logs --no-log-prefix web | jq` parses. They share one log_json,
docker/web/scripts/log_json.sh, which the image copies to /zenysis/log_json.sh."""

import json
import re
import subprocess
from datetime import datetime

import pytest
from test_run_web_gunicorn import REPO, pytestmark, run  # noqa: F401

LIBRARY = REPO / 'docker/web/scripts/log_json.sh'
SCRIPTS = [
    'docker/entrypoint_web.sh',
    'docker/web/scripts/initialize_new_container.sh',
    'docker/web/scripts/run_web_gunicorn.sh',
]
DEFINITION = re.compile(r'^\s*(function\s+)?log_json\s*\(\)', re.M)


@pytest.mark.parametrize('script', SCRIPTS)
def test_scripts_print_no_plain_text(script):
    plain = [
        line
        for line in (REPO / script).read_text().splitlines()
        if re.match(r'\s*echo\b', line)
    ]
    assert not plain


def test_log_json_is_defined_once():
    defined = [
        str(path.relative_to(REPO))
        for path in sorted((REPO / 'docker').rglob('*.sh'))
        if DEFINITION.search(path.read_text())
    ]
    assert defined == [str(LIBRARY.relative_to(REPO))]


@pytest.mark.parametrize('script', SCRIPTS)
def test_scripts_source_the_shared_log_json(script):
    sources = re.findall(
        r'^\s*(?:source|\.)\s+(.*log_json\.sh\S*)$', (REPO / script).read_text(), re.M
    )
    assert len(sources) == 1, script


def test_log_json_writes_one_json_line_named_after_the_caller(tmp_path):
    caller = tmp_path / 'some_script.sh'
    caller.write_text(f'source {LIBRARY}\nlog_json "Running server..."\n')
    result = subprocess.run(
        ['bash', str(caller)], capture_output=True, text=True, check=True
    )
    (line,) = result.stdout.splitlines()
    entry = json.loads(line)
    assert entry['level'] == 'INFO'
    assert entry['logger'] == 'some_script.sh'
    assert entry['message'] == 'Running server...'
    assert datetime.fromisoformat(entry['timestamp']).utcoffset().total_seconds() == 0


def test_run_web_gunicorn_status_lines_are_json(tmp_path):
    result = run(tmp_path, 'exit 0')
    lines = result.stdout.splitlines()
    assert lines
    messages = [json.loads(line)['message'] for line in lines]
    assert messages[-1] == 'Master gunicorn process has ended.'
