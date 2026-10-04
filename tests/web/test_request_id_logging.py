from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from celery import Celery
from celery.contrib.testing.worker import start_worker
from flask import Flask
from flask_jwt_extended import JWTManager
from flask_login import LoginManager, current_user

from log import LOG
from log.celery_signals import connect_celery_logging
from log.config import configure_logging
from log.context import REQUEST_ID_HEADER, current_request_id
from log.flask_request import install_request_logging

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
GENERATED_ID = re.compile(r'[0-9a-f]{32}')

# Values that must never reach a log line. Distinctive so a hit is unambiguous.
SENTINELS = {
    'DEFAULT_SECRET_KEY': 'wp2g-sentinel-session-key-0123456789abcdef',
    'JWT_SECRET_KEY': 'wp2g-sentinel-jwt-key-0123456789abcdef0123',
    'password': 'wp2g-sentinel-password',
    'database password': 'wp2gsentineldbpw',
    'HASURA_ADMIN_SECRET': 'wp2g-sentinel-hasura-admin',
    'EMAIL_HOST_PASSWORD': 'wp2g-sentinel-smtp',
    'MAPBOX_ACCESS_TOKEN': 'wp2g-sentinel-mapbox',
    'REDIS_PASSWORD': 'wp2g-sentinel-redis',
}


class LogLines:
    def __init__(self, stream: io.StringIO) -> None:
        self.stream = stream

    def entries(self) -> list[dict]:
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]

    def with_message(self, message: str) -> list[dict]:
        return [entry for entry in self.entries() if entry['message'] == message]


@pytest.fixture(name='log_lines')
def fixture_log_lines(monkeypatch) -> Iterator[LogLines]:
    monkeypatch.setenv('LOG_FORMAT', 'json')
    monkeypatch.setenv('LOG_LEVEL', 'DEBUG')
    saved_hook = sys.excepthook
    configure_logging()
    stream = io.StringIO()
    for handler in logging.getLogger().handlers:
        if type(handler) is logging.StreamHandler:
            handler.setStream(stream)
    yield LogLines(stream)
    sys.excepthook = saved_hook
    monkeypatch.delenv('LOG_FORMAT')
    monkeypatch.delenv('LOG_LEVEL')
    configure_logging()


@pytest.fixture(name='app')
def fixture_app(bare_flask_app) -> Flask:
    app = bare_flask_app()
    install_request_logging(app)

    @app.route('/hello')
    def hello():
        LOG.info('handling hello')
        return 'ok'

    return app


def test_a_well_formed_request_id_is_kept_and_echoed(app, log_lines):
    response = app.test_client().get(
        '/hello', headers={REQUEST_ID_HEADER: 'nginx-1a2b'}
    )
    assert response.headers[REQUEST_ID_HEADER] == 'nginx-1a2b'
    (entry,) = log_lines.with_message('handling hello')
    assert entry['request_id'] == 'nginx-1a2b'


def test_a_request_without_an_id_gets_one(app, log_lines):
    response = app.test_client().get('/hello')
    request_id = response.headers[REQUEST_ID_HEADER]
    assert GENERATED_ID.fullmatch(request_id)
    (entry,) = log_lines.with_message('handling hello')
    assert entry['request_id'] == request_id


@pytest.mark.parametrize(
    'header',
    ['two words', 'quote"d', 'x' * 129, 'new\\nline', ''],
)
def test_a_malformed_request_id_is_replaced(app, log_lines, header):
    response = app.test_client().get('/hello', headers={REQUEST_ID_HEADER: header})
    request_id = response.headers[REQUEST_ID_HEADER]
    assert GENERATED_ID.fullmatch(request_id)
    (entry,) = log_lines.with_message('handling hello')
    assert entry['request_id'] == request_id


def test_each_request_gets_its_own_id_and_nothing_leaks_after(app, log_lines):
    client = app.test_client()
    first = client.get('/hello').headers[REQUEST_ID_HEADER]
    second = client.get('/hello').headers[REQUEST_ID_HEADER]
    assert first != second
    assert [e['request_id'] for e in log_lines.with_message('handling hello')] == [
        first,
        second,
    ]
    assert current_request_id() is None
    LOG.info('between requests')
    (entry,) = log_lines.with_message('between requests')
    assert 'request_id' not in entry


def test_the_app_sees_the_effective_request_id(app):
    @app.route('/echo')
    def echo():
        from flask import request

        return request.headers[REQUEST_ID_HEADER]

    response = app.test_client().get('/echo', headers={REQUEST_ID_HEADER: 'bad id'})
    assert response.get_data(as_text=True) == response.headers[REQUEST_ID_HEADER]


@pytest.fixture(name='app_with_users')
def fixture_app_with_users(app) -> Flask:
    login_manager = LoginManager(app)

    @login_manager.request_loader
    def load_user(request):
        user_id = request.headers.get('X-Test-User')
        if not user_id:
            return None
        return SimpleNamespace(
            id=int(user_id), is_authenticated=True, is_active=True, is_anonymous=False
        )

    @app.route('/who')
    def who():
        LOG.info('user is %s', 'known' if current_user.is_authenticated else 'anon')
        return 'ok'

    return app


def test_lines_carry_the_loaded_users_id(app_with_users, log_lines):
    client = app_with_users.test_client()
    client.get('/who', headers={'X-Test-User': '7'})
    client.get('/who')
    assert [
        e.get('user_id') for e in log_lines.entries() if e['logger'] == 'ZenysisLogger'
    ] == [7, None]


def test_logging_does_not_load_the_user(app_with_users, log_lines):
    app_with_users.test_client().get('/hello', headers={'X-Test-User': '7'})
    (entry,) = log_lines.with_message('handling hello')
    assert 'user_id' not in entry


@pytest.fixture(name='celery_app')
def fixture_celery_app() -> Celery:
    connect_celery_logging()
    celery_app = Celery('wp2g-test', broker='memory://', backend='cache+memory://')

    @celery_app.task(name='wp2g.log_in_task')
    def log_in_task(label):
        LOG.info('in task %s', label)
        return label

    return celery_app


def _route_sending(app: Flask, task) -> None:
    @app.route('/send')
    def send():
        result = task.delay('send')
        return result.get(timeout=20)


def test_an_eager_task_logs_with_the_requests_id(app, celery_app, log_lines):
    celery_app.conf.task_always_eager = True
    _route_sending(app, celery_app.tasks['wp2g.log_in_task'])
    response = app.test_client().get('/send')
    (entry,) = log_lines.with_message('in task send')
    assert entry['request_id'] == response.headers[REQUEST_ID_HEADER]
    assert entry['task'] == 'wp2g.log_in_task'
    assert entry['task_id']


def test_a_published_task_carries_the_request_id_to_the_worker(
    app, celery_app, log_lines
):
    _route_sending(app, celery_app.tasks['wp2g.log_in_task'])
    with start_worker(celery_app, pool='solo', perform_ping_check=False):
        response = app.test_client().get('/send')
    (entry,) = log_lines.with_message('in task send')
    # The worker runs the task in its own thread, so the id can only have come from
    # the message headers.
    assert entry['request_id'] == response.headers[REQUEST_ID_HEADER]
    assert entry['task'] == 'wp2g.log_in_task'
    assert entry['task_id']
    (succeeded,) = [
        e
        for e in log_lines.entries()
        if e['logger'] == 'celery.app.trace' and 'succeeded' in e['message']
    ]
    assert succeeded['request_id'] == entry['request_id']
    assert succeeded['task_id'] == entry['task_id']
    startup = [
        e
        for e in log_lines.entries()
        if e['logger'] == 'celery.worker.consumer.connection'
    ]
    assert startup and all('request_id' not in e for e in startup)


def test_a_task_published_outside_a_request_has_no_request_id(celery_app, log_lines):
    with start_worker(celery_app, pool='solo', perform_ping_check=False):
        assert (
            celery_app.tasks['wp2g.log_in_task'].delay('beat').get(timeout=20) == 'beat'
        )
    (entry,) = log_lines.with_message('in task beat')
    assert 'request_id' not in entry
    assert entry['task'] == 'wp2g.log_in_task'


def _assert_no_sentinel(text: str) -> None:
    leaked = [name for name, value in SENTINELS.items() if value in text]
    assert not leaked, f'{leaked} reached the logs'


def test_login_attempts_log_no_secret(bare_flask_app, log_lines):
    from web.server.security.signal_handlers import (
        install_login_manager_signal_handlers,
    )
    from web.server.util.authentication import login_user

    app = bare_flask_app()
    app.config.update(
        SECRET_KEY=SENTINELS['DEFAULT_SECRET_KEY'],
        JWT_SECRET_KEY=SENTINELS['JWT_SECRET_KEY'],
        JWT_TOKEN_LOCATION=['headers', 'cookies'],
        JWT_ACCESS_COOKIE_NAME='accessKey',
        JWT_CSRF_METHODS=[],
        JWT_TOKEN_WEB_COOKIE_EXPIRATION=__import__('datetime').timedelta(days=1),
    )
    JWTManager(app)
    login_manager = LoginManager(app)
    app.cache = SimpleNamespace(memoize=lambda: lambda function: function)
    app.user_manager = SimpleNamespace(find_user_by_username=lambda username: None)
    install_login_manager_signal_handlers(app, login_manager)
    install_request_logging(app)

    @app.route('/api/me')
    def me():
        LOG.info('authenticated: %s', current_user.is_authenticated)
        return 'ok'

    @app.route('/api/login', methods=['POST'])
    def login():
        LOG.info('login form received')
        return login_user('login_successful', 'analyst@example.org')

    client = app.test_client()
    password = SENTINELS['password']
    client.get(
        '/api/me', headers={'X-Username': 'analyst@example.org', 'X-Password': password}
    )
    issued = client.post(
        '/api/login', data={'username': 'analyst@example.org', 'password': password}
    )
    token = issued.headers['Set-Cookie'].split('accessKey=', 1)[1].split(';', 1)[0]
    client.get('/api/me', headers={'Authorization': f'Bearer {password}.{password}'})
    client.get('/api/me', headers={'Cookie': f'accessKey={password}'})

    text = log_lines.stream.getvalue()
    _assert_no_sentinel(text)
    assert token not in text
    assert log_lines.with_message("User: 'analyst@example.org' failed to authenticate.")
    assert log_lines.with_message('login form received')


def test_app_startup_logs_no_secret():
    pytest.importorskip('flask_migrate')
    env = {
        'PATH': os.environ['PATH'],
        'PYTHONPATH': REPO_ROOT,
        'ZEN_ENV': 'harmony_demo',
        'DRUID_HOST': 'http://druid.invalid',
        'LOG_FORMAT': 'json',
        'LOG_LEVEL': 'DEBUG',
        'DEFAULT_SECRET_KEY': SENTINELS['DEFAULT_SECRET_KEY'],
        'JWT_SECRET_KEY': SENTINELS['JWT_SECRET_KEY'],
        'HASURA_ADMIN_SECRET': SENTINELS['HASURA_ADMIN_SECRET'],
        'EMAIL_HOST_PASSWORD': SENTINELS['EMAIL_HOST_PASSWORD'],
        'MAPBOX_ACCESS_TOKEN': SENTINELS['MAPBOX_ACCESS_TOKEN'],
        'REDIS_PASSWORD': SENTINELS['REDIS_PASSWORD'],
        'DATABASE_URL': f"postgresql://zen:{SENTINELS['database password']}@db.invalid",
        'SQLALCHEMY_DATABASE_URI': (
            f"postgresql://zen:{SENTINELS['database password']}@db.invalid/zen"
        ),
    }
    script = (
        'from web.server.app import create_app\n'
        'app = create_app(skip_db_check=True)\n'
        "app.test_client().get('/', headers={'Authorization': 'Bearer x'})\n"
    )
    result = subprocess.run(
        [sys.executable, '-c', script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    _assert_no_sentinel(result.stdout + result.stderr)
    lines = result.stderr.splitlines()
    assert lines, 'startup wrote no log lines'
    entries = [json.loads(line) for line in lines]
    assert {entry['deployment'] for entry in entries} == {'harmony_demo'}
