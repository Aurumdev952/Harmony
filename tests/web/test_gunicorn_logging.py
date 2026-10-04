from __future__ import annotations

import importlib
import io
import json
import logging
import sys
from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from log.config import configure_logging, logging_config

pytest.importorskip('gunicorn')

# pylint: disable=wrong-import-position
from gunicorn.config import Config  # noqa: E402
from gunicorn.glogging import Logger  # noqa: E402


@pytest.fixture(name='gunicorn_logger')
def fixture_gunicorn_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Logger, io.StringIO]]:
    monkeypatch.setenv('LOG_FORMAT', 'json')
    monkeypatch.setenv('ZEN_ENV', 'rw')
    saved_hook = sys.excepthook
    config = Config()
    config.set('logconfig_dict', logging_config())
    logger = Logger(config)
    stream = io.StringIO()
    for handler in logging.getLogger().handlers:
        if type(handler) is logging.StreamHandler:
            handler.setStream(stream)
    yield logger, stream
    sys.excepthook = saved_hook
    monkeypatch.delenv('LOG_FORMAT')
    configure_logging()


def _access(
    logger: Logger, path: str, query: str, headers: list[tuple[str, str]]
) -> None:
    response = SimpleNamespace(status='200 OK', sent=1234, headers=headers)
    request = SimpleNamespace(headers=[('USER-AGENT', 'Mozilla/5.0')])
    environ = {
        'REMOTE_ADDR': '172.18.0.5',
        'REQUEST_METHOD': 'GET',
        'RAW_URI': f'{path}?{query}',
        'PATH_INFO': path,
        'QUERY_STRING': query,
        'SERVER_PROTOCOL': 'HTTP/1.1',
    }
    logger.access(response, request, environ, timedelta(milliseconds=42))


def _entries(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_access_lines_are_json_with_the_response_request_id(
    gunicorn_logger: tuple[Logger, io.StringIO],
) -> None:
    logger, stream = gunicorn_logger
    _access(logger, '/api/query', 'token=abc', [('X-Request-ID', 'req-42')])
    (entry,) = _entries(stream)
    assert entry['logger'] == 'gunicorn.access'
    assert entry['level'] == 'INFO'
    assert entry['message'] == 'GET /api/query 200'
    assert entry['request_id'] == 'req-42'
    assert entry['deployment'] == 'rw'
    assert entry['http'] == {
        'method': 'GET',
        'path': '/api/query',
        'status': 200,
        'bytes': 1234,
        'duration_s': 0.042,
    }
    assert 'abc' not in stream.getvalue()


def test_access_lines_redact_tokens_in_the_path(
    gunicorn_logger: tuple[Logger, io.StringIO],
) -> None:
    logger, stream = gunicorn_logger
    _access(logger, '/user/reset-password/ResetTok.abc', '', [])
    (entry,) = _entries(stream)
    assert 'ResetTok' not in stream.getvalue()
    assert 'request_id' not in entry


def test_gunicorn_error_lines_share_the_handler(
    gunicorn_logger: tuple[Logger, io.StringIO],
) -> None:
    logger, stream = gunicorn_logger
    logger.info('Booting worker with pid: %s', 7)
    (entry,) = _entries(stream)
    assert entry['logger'] == 'gunicorn.error'
    assert entry['message'] == 'Booting worker with pid: 7'
    gunicorn_handlers = logging.getLogger('gunicorn.error').handlers
    assert gunicorn_handlers == [], 'gunicorn handlers must defer to the root handler'


def test_gunicorn_server_hands_the_log_config_to_gunicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gevent_monkey = pytest.importorskip('gevent.monkey')
    # The module monkey-patches the process and imports the whole web app at import;
    # neither belongs in the test process.
    monkeypatch.setattr(gevent_monkey, 'patch_all', lambda: None)
    monkeypatch.setitem(
        sys.modules, 'web.server.app', SimpleNamespace(create_app=lambda: None)
    )
    monkeypatch.delitem(sys.modules, 'web.gunicorn_server', raising=False)
    monkeypatch.setenv('SERVER_SOFTWARE', 'pytest')
    server = importlib.import_module('web.gunicorn_server')

    loaded: dict[str, Any] = {}
    monkeypatch.setattr(
        server.GunicornApplication,
        'run',
        lambda self: loaded.update(logconfig_dict=self.cfg.logconfig_dict),
    )
    monkeypatch.setattr(sys, 'argv', ['gunicorn_server.py'])
    server.main()

    assert loaded['logconfig_dict'] == logging_config()
