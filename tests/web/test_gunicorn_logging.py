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
from gunicorn.http.errors import (  # noqa: E402
    ChunkMissingTerminator,
    InvalidChunkSize,
    InvalidHeader,
    InvalidRequestLine,
    NoMoreData,
)


@pytest.fixture(name='gunicorn_logger')
def fixture_gunicorn_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Logger, io.StringIO]]:
    yield from _gunicorn_logger(monkeypatch, 'json')


@pytest.fixture(name='any_format_logger', params=['json', 'text'])
def fixture_any_format_logger(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[tuple[Logger, io.StringIO]]:
    yield from _gunicorn_logger(monkeypatch, request.param)


def _gunicorn_logger(
    monkeypatch: pytest.MonkeyPatch, log_format: str
) -> Iterator[tuple[Logger, io.StringIO]]:
    monkeypatch.setenv('LOG_FORMAT', log_format)
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
    logger: Logger,
    path: str,
    query: str,
    headers: list[tuple[str, str]],
    request_headers: tuple[tuple[str, str], ...] = (),
) -> None:
    response = SimpleNamespace(status='200 OK', sent=1234, headers=headers)
    request = SimpleNamespace(headers=[('USER-AGENT', 'Mozilla/5.0'), *request_headers])
    environ = {
        'REMOTE_ADDR': '172.18.0.5',
        'REQUEST_METHOD': 'GET',
        'RAW_URI': f'{path}?{query}',
        'PATH_INFO': path,
        'QUERY_STRING': query,
        'SERVER_PROTOCOL': 'HTTP/1.1',
    }
    for name, value in request_headers:
        environ['HTTP_' + name.replace('-', '_')] = value
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


# Values that must never reach a log line. Each is unique, so a substring check
# cannot pass by accident.
QUERY_SECRETS = {'token': 'QTOK1', 'api_key': 'QKEY1', 'password': 'QPWD1'}
OTHER_QUERY_VALUE = 'QCODE1'
SENSITIVE_HEADERS = (
    ('AUTHORIZATION', 'Bearer HDRBEARER1'),
    ('COOKIE', 'session=SESSCOOKIE1; accessKey=ACCESSKEY1'),
    ('REFERER', 'https://zz.example.org/login?token=REFTOK1'),
)
BASIC_AUTH = ('AUTHORIZATION', 'Basic YWxpY2U6QkFTSUNQVzE=')  # alice:BASICPW1


def _assert_absent(output: str, *values: str) -> None:
    leaked = [value for value in values if value in output]
    assert not leaked, f'{leaked} leaked into: {output}'


def test_access_lines_carry_no_query_header_or_cookie_secrets(
    any_format_logger: tuple[Logger, io.StringIO],
) -> None:
    logger, stream = any_format_logger
    query = '&'.join(f'{k}={v}' for k, v in QUERY_SECRETS.items())
    _access(
        logger,
        '/api/query',
        f'{query}&code={OTHER_QUERY_VALUE}',
        [('Set-Cookie', 'session=SETCOOKIE1; HttpOnly'), ('X-Request-ID', 'req-7')],
        SENSITIVE_HEADERS,
    )
    _access(logger, '/api/query', '', [], (BASIC_AUTH,))
    output = stream.getvalue()
    lines = output.splitlines()
    assert len(lines) == 2
    assert all('GET /api/query 200' in line for line in lines)
    _assert_absent(
        output,
        *QUERY_SECRETS.values(),
        OTHER_QUERY_VALUE,
        'HDRBEARER1',
        'SESSCOOKIE1',
        'ACCESSKEY1',
        'REFTOK1',
        'SETCOOKIE1',
        'YWxpY2U6QkFTSUNQVzE',
        'alice',
        'BASICPW1',
    )


def test_text_access_lines_carry_the_response_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for logger, stream in _gunicorn_logger(monkeypatch, 'text'):
        _access(logger, '/api/query', '', [('X-Request-ID', 'req-8')])
        (line,) = stream.getvalue().splitlines()
        assert 'GET /api/query 200' in line
        assert 'request_id=req-8' in line


def test_error_lines_drop_query_strings(
    any_format_logger: tuple[Logger, io.StringIO],
) -> None:
    logger, stream = any_format_logger
    try:
        raise RuntimeError('view failed')
    except RuntimeError:
        logger.exception(
            'Error handling request %s',
            f'/api/query?code={OTHER_QUERY_VALUE}&token=QTOK1',
        )
    logger.error(
        'Invalid request from ip=192.0.2.1: %s',
        InvalidRequestLine(f'GET /x?code={OTHER_QUERY_VALUE} HTTP/1.1'),
    )
    output = stream.getvalue()
    assert '/api/query' in output
    assert 'view failed' in output
    _assert_absent(output, OTHER_QUERY_VALUE, 'QTOK1')


@pytest.mark.parametrize(
    'error',
    [
        NoMoreData(b'{"note": "BODYTEXT1"}'),
        InvalidChunkSize(b'BODYTEXT1'),
        ChunkMissingTerminator(b'BODYTEXT1'),
        InvalidHeader('Authorization: Basic HDRBASIC1'),
        InvalidHeader('Cookie: session=SESSCOOKIE1'),
    ],
    ids=lambda error: type(error).__name__,
)
def test_error_lines_do_not_echo_request_bodies_or_headers(
    any_format_logger: tuple[Logger, io.StringIO], error: Exception
) -> None:
    logger, stream = any_format_logger
    try:
        raise error
    except type(error):
        logger.exception('Error handling request %s', '/api/upload')
    logger.error('Invalid request from ip=192.0.2.1: %s', error)
    output = stream.getvalue()
    assert '/api/upload' in output
    assert type(error).__name__ in output
    _assert_absent(output, 'BODYTEXT1', 'HDRBASIC1', 'SESSCOOKIE1')


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
