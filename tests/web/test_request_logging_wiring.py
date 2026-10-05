'''The app wires WP-2g's request logging in itself: `create_app` installs the request
id middleware, `create_celery` connects the Celery signals, and the request logger
uses the same id.
'''

from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from celery import Celery, signals
from celery.contrib.testing.worker import start_worker
from flask import Flask

from log import LOG
from log.config import configure_logging
from log.context import REQUEST_ID_HEADER
from log.flask_request import install_request_logging

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
GENERATED_ID = re.compile(r'[0-9a-f]{32}')

# Outside gunicorn, create_app skips _initialize_app, which sets up Flask-User and
# connects initialize_request_logger; the script does both the same way.
CREATE_APP_SCRIPT = '''
import json

from flask import g, request_started
from flask_login import LoginManager

from web.server.app import create_app
from web.server.security.signal_handlers import initialize_request_logger

app = create_app(skip_db_check=True)
LoginManager(app)
request_started.connect(initialize_request_logger, app)


@app.route('/wp2g-view')
def view():
    g.request_logger.info('wp2g view line')
    return str(g.request_id)


client = app.test_client()
for headers in ({}, {'X-Request-ID': 'nginx-1a2b'}):
    response = client.get('/wp2g-view', headers=headers)
    print(json.dumps({
        'status': response.status_code,
        'header': response.headers.get('X-Request-ID'),
        'g_request_id': response.get_data(as_text=True),
    }))
'''


def test_create_app_requests_share_one_id_across_header_view_line_and_g() -> None:
    pytest.importorskip('flask_migrate')
    env = {
        'PATH': os.environ['PATH'],
        'PYTHONPATH': REPO_ROOT,
        'ZEN_ENV': 'harmony_demo',
        'DRUID_HOST': 'http://druid.invalid',
        'DEFAULT_SECRET_KEY': 'tests-web-wiring-key-0123456789abcdef',
        'SQLALCHEMY_DATABASE_URI': 'postgresql://zen@db.invalid/zen',
        'LOG_FORMAT': 'json',
        'LOG_STREAM': 'stderr',
    }
    result = subprocess.run(
        [sys.executable, '-c', CREATE_APP_SCRIPT],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    view_lines = [
        entry
        for entry in map(json.loads, result.stderr.splitlines())
        if entry['message'] == 'wp2g view line'
    ]

    assert [r['status'] for r in responses] == [200, 200]
    generated, forwarded = (r['header'] for r in responses)
    assert generated and GENERATED_ID.fullmatch(generated)
    assert forwarded == 'nginx-1a2b'
    assert [r['g_request_id'] for r in responses] == [generated, forwarded]
    assert [line['request_id'] for line in view_lines] == [generated, forwarded]


class LogLines:
    def __init__(self, stream: io.StringIO) -> None:
        self.stream = stream

    def with_message(self, message: str) -> list[dict[str, Any]]:
        entries = [json.loads(line) for line in self.stream.getvalue().splitlines()]
        return [entry for entry in entries if entry['message'] == message]


@pytest.fixture(name='log_lines')
def fixture_log_lines(monkeypatch: pytest.MonkeyPatch) -> Iterator[LogLines]:
    monkeypatch.setenv('LOG_FORMAT', 'json')
    saved_hook = sys.excepthook
    configure_logging()
    stream = io.StringIO()
    for handler in logging.getLogger().handlers:
        if type(handler) is logging.StreamHandler:
            handler.setStream(stream)
    yield LogLines(stream)
    sys.excepthook = saved_hook
    monkeypatch.delenv('LOG_FORMAT')
    configure_logging()


CELERY_LOGGING_SIGNALS = (
    signals.setup_logging,
    signals.before_task_publish,
    signals.task_prerun,
    signals.task_postrun,
)


@pytest.fixture(name='celery_logging_disconnected')
def fixture_celery_logging_disconnected() -> None:
    # Other tests connect the receivers directly; start from none connected.
    for signal in CELERY_LOGGING_SIGNALS:
        signal.disconnect(dispatch_uid='log.celery_signals')


def test_create_celery_carries_the_request_id_into_a_worker_task(
    bare_flask_app: Any,
    log_lines: LogLines,
    monkeypatch: pytest.MonkeyPatch,
    celery_logging_disconnected: None,
) -> None:
    from web.server.workers import create_celery

    monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', 'postgresql://zen@db.invalid/zen')
    create_celery({})

    worker_app = Celery('wp2g-wiring', broker='memory://', backend='cache+memory://')

    def log_in_task() -> str:
        LOG.info('in wiring task')
        return 'done'

    wiring_task = worker_app.task(name='wp2g.wiring_task')(log_in_task)

    app: Flask = bare_flask_app()
    install_request_logging(app)

    @app.route('/send')
    def send() -> str:
        return str(wiring_task.delay().get(timeout=20))

    with start_worker(worker_app, pool='solo', perform_ping_check=False):
        response = app.test_client().get('/send')

    assert response.get_data(as_text=True) == 'done'
    (entry,) = log_lines.with_message('in wiring task')
    # The worker runs the task in its own thread, so the id came from the headers.
    assert entry['request_id'] == response.headers[REQUEST_ID_HEADER]
    assert entry['task'] == 'wp2g.wiring_task'
    assert entry['task_id']
