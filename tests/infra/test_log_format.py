from __future__ import annotations

import io
import json
import logging
import logging.handlers
import re
import sys
import time
from datetime import datetime, timezone

import pytest

from log import context
from log.config import (
    JsonFormatter,
    TextFormatter,
    configure_logging,
    logging_config,
    redact,
)


def _record(
    message: str = 'hello %s',
    args: tuple[object, ...] = ('world',),
    level: int = logging.INFO,
    name: str = 'ZenysisLogger',
    exc_info: object = None,
) -> logging.LogRecord:
    return logging.LogRecord(
        name, level, '/zenysis/web/server/app.py', 42, message, args, exc_info, 'start'
    )


def _json(record: logging.LogRecord, deployment: str | None = 'rw') -> dict:
    line = JsonFormatter(deployment=deployment).format(record)
    assert '\n' not in line
    return json.loads(line)


def _raised() -> tuple:
    try:
        raise ValueError('boom')
    except ValueError:
        return sys.exc_info()


def test_json_line_has_the_required_keys():
    entry = _json(_record())
    assert entry['level'] == 'INFO'
    assert entry['logger'] == 'ZenysisLogger'
    assert entry['message'] == 'hello world'
    assert entry['source'] == 'app.py:start:42'
    assert entry['deployment'] == 'rw'
    parsed = datetime.fromisoformat(entry['timestamp'])
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)
    assert 'request_id' not in entry and 'user_id' not in entry
    assert 'exc_info' not in entry


def test_json_line_takes_deployment_from_zen_env(monkeypatch):
    monkeypatch.setenv('ZEN_ENV', 'et')
    assert _json(_record(), deployment=None)['deployment'] == 'et'
    monkeypatch.delenv('ZEN_ENV')
    assert 'deployment' not in _json(_record(), deployment=None)


def test_json_line_carries_bound_request_id_and_user_id():
    token = context.bind(request_id='abc123')
    context.set_user_id_provider(lambda: 7)
    try:
        entry = _json(_record())
    finally:
        context.set_user_id_provider(None)
        context.reset(token)
    assert entry['request_id'] == 'abc123'
    assert entry['user_id'] == 7
    assert 'request_id' not in _json(_record())


def test_a_failing_user_id_provider_does_not_break_logging():
    def provider() -> int:
        raise RuntimeError('no request')

    context.set_user_id_provider(provider)
    try:
        entry = _json(_record())
    finally:
        context.set_user_id_provider(None)
    assert 'user_id' not in entry


def test_request_id_from_a_logger_adapter_is_the_fallback():
    record = _record()
    record.request_id = 'from-adapter'
    assert _json(record)['request_id'] == 'from-adapter'
    token = context.bind(request_id='from-context')
    try:
        assert _json(record)['request_id'] == 'from-context'
    finally:
        context.reset(token)


def test_json_line_carries_exception_info_on_one_line():
    entry = _json(_record('failed', (), logging.ERROR, exc_info=_raised()))
    assert entry['level'] == 'ERROR'
    assert 'Traceback' in entry['exc_info']
    assert 'ValueError: boom' in entry['exc_info']


def test_non_ascii_messages_survive():
    assert _json(_record('Données %s', ('ጤና',)))['message'] == 'Données ጤና'


def test_text_line_is_readable_with_context():
    formatter = TextFormatter()
    plain = formatter.format(_record())
    assert re.fullmatch(
        r'\d{8}\.\d{6}\.\d{3} INFO app\.py:start:42: hello world', plain
    ), plain
    token = context.bind(request_id='abc123')
    try:
        bound = formatter.format(_record())
    finally:
        context.reset(token)
    assert bound.endswith(': hello world [request_id=abc123]'), bound


@pytest.mark.parametrize(
    'raw, secret',
    [
        ('Authorization: Bearer abc.def-ghi', 'abc.def-ghi'),
        ('headers {"Authorization": "Basic dXNlcjpodW50ZXIy"}', 'dXNlcjpodW50ZXIy'),
        ('got bearer s3cr3tT0ken', 's3cr3tT0ken'),
        (
            'jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJlLXZhbHVl here',
            'eyJzdWIiOiJ4In0',
        ),
        ('broker redis://:hunter2@redis:6379/0', 'hunter2'),
        ('db postgresql://zen:hunter2@db/zenysis', 'hunter2'),
        ('Cookie: accessKey=abc123; session=def456', 'abc123'),
        ('set accessKey=abc123; Path=/', 'abc123'),
        ("kwargs {'email_host_password': 'hunter2', 'port': 25}", 'hunter2'),
        ('JWT_SECRET_KEY=hunter2hunter2', 'hunter2hunter2'),
        ('GET /user/register?token=InviteTok.abc&next=/', 'InviteTok.abc'),
        ('GET /user/reset-password/ResetTok.abc.def HTTP/1.1', 'ResetTok.abc.def'),
        ('password: hunter2', 'hunter2'),
        ("{'api_key': 'k-123'}", 'k-123'),
        ('X-Hasura-Admin-Secret: adm1n', 'adm1n'),
        # gunicorn body-parsing errors, as they appear in app tracebacks.
        ('NoMoreData: No more data after: b\'{"note": "b0dy"}\'', 'b0dy'),
        ("InvalidChunkSize: Invalid chunk size: b'b0dy'", 'b0dy'),
        (
            "Invalid chunk terminator is not '\\r\\n': b'b0dy\\r\\nmore'",
            'b0dy',
        ),
    ],
)
def test_redact_removes_secret_values(raw, secret):
    redacted = redact(raw)
    assert secret not in redacted, redacted
    assert '[REDACTED]' in redacted


@pytest.mark.parametrize(
    'message',
    [
        'Invalid token',
        'DEFAULT_SECRET_KEY is unset, empty or the default "changeme"; refusing.',
        'Database schema version is: 9a628ffd6795',
        'User \'7\' logged in',
        'GET /api/v1/query 200',
        # Query strings are stripped only from gunicorn's client URIs.
        'Fetching http://druid:8082/druid/v2/?pretty',
    ],
)
def test_redact_keeps_ordinary_messages(message):
    assert redact(message) == message


def test_secrets_are_redacted_in_formatted_lines_and_tracebacks():
    try:
        raise RuntimeError('cannot reach redis://:hunter2@redis:6379')
    except RuntimeError:
        exc_info = sys.exc_info()
    record = _record('login with password=%s', ('hunter2',), exc_info=exc_info)
    json_line = JsonFormatter(deployment=None).format(record)
    text_line = TextFormatter().format(record)
    assert 'hunter2' not in json_line
    assert 'hunter2' not in text_line


@pytest.mark.parametrize(
    'env, expected',
    [
        ({}, TextFormatter),
        ({'ZEN_PROD': '1'}, JsonFormatter),
        ({'LOG_FORMAT': 'json'}, JsonFormatter),
        ({'ZEN_PROD': '1', 'LOG_FORMAT': 'text'}, TextFormatter),
    ],
)
def test_format_follows_the_environment(monkeypatch, env, expected):
    for name in ('ZEN_PROD', 'LOG_FORMAT', 'LOG_LEVEL'):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    formatter = logging_config()['formatters']['default']['()']
    assert formatter is expected


def test_unknown_format_is_refused(monkeypatch):
    monkeypatch.setenv('LOG_FORMAT', 'xml')
    with pytest.raises(ValueError, match='LOG_FORMAT'):
        logging_config()


def test_unknown_stream_is_refused(monkeypatch):
    monkeypatch.setenv('LOG_STREAM', 'file')
    with pytest.raises(ValueError, match='LOG_STREAM'):
        logging_config()


@pytest.mark.parametrize(
    'stream, expected', [(None, 'ext://sys.stderr'), ('stdout', 'ext://sys.stdout')]
)
def test_config_has_one_stream_handler_and_no_files(monkeypatch, stream, expected):
    monkeypatch.setenv('LOG_LEVEL', 'debug')
    monkeypatch.delenv('LOG_STREAM', raising=False)
    if stream:
        monkeypatch.setenv('LOG_STREAM', stream)
    config = logging_config()
    assert config['root'] == {'level': 'DEBUG', 'handlers': ['stream']}
    assert list(config['handlers']) == ['stream']
    assert config['handlers']['stream']['stream'] == expected
    assert all(
        logger.get('propagate', True) and not logger.get('handlers')
        for logger in config['loggers'].values()
    )


def _our_handlers() -> list[logging.Handler]:
    # pytest adds its own capture handlers (StreamHandler subclasses) to the root.
    return [h for h in logging.getLogger().handlers if type(h) is logging.StreamHandler]


@pytest.fixture(name='configured')
def fixture_configured(monkeypatch):
    monkeypatch.setenv('LOG_FORMAT', 'json')
    monkeypatch.setenv('LOG_STREAM', 'stdout')
    monkeypatch.setenv('ZEN_ENV', 'rw')
    saved_hook = sys.excepthook
    configure_logging()
    configure_logging()
    (handler,) = _our_handlers()
    assert handler.stream is sys.stdout
    stream = io.StringIO()
    handler.setStream(stream)
    yield stream
    sys.excepthook = saved_hook
    monkeypatch.delenv('LOG_FORMAT')
    monkeypatch.delenv('LOG_STREAM')
    configure_logging()


def _lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_configured_loggers_write_json_to_the_stream_once(configured):
    assert not any(
        isinstance(handler, logging.handlers.RotatingFileHandler)
        for handler in logging.getLogger().handlers
    )
    logging.getLogger('ZenysisLogger').info('from the app')
    logging.getLogger('celery.worker').warning('from a library')
    entries = _lines(configured)
    assert [(e['logger'], e['message']) for e in entries] == [
        ('ZenysisLogger', 'from the app'),
        ('celery.worker', 'from a library'),
    ]
    assert {e['deployment'] for e in entries} == {'rw'}


def test_uncaught_exception_is_one_error_line_without_the_value(configured):
    try:
        raise RuntimeError(
            'JWT_SECRET_KEY equals DEFAULT_SECRET_KEY; refusing to start.'
        )
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    (entry,) = _lines(configured)
    assert entry['level'] == 'ERROR'
    assert entry['message'] == (
        'Uncaught RuntimeError: JWT_SECRET_KEY equals DEFAULT_SECRET_KEY; '
        'refusing to start.'
    )
    assert 'Traceback' in entry['exc_info']


# Client-controlled text (paths, headers, bodies) reaches these patterns on access
# and error lines inside a gevent worker, so formatting must stay linear in it.
# 8000 bytes is gunicorn's header field limit. Before the patterns were anchored to
# the start of a run, these took from a tenth of a second to over a minute.
_HOSTILE = {
    'a-a-a': 'a-' * 4000,
    'path': '/' + 'a-' * 4000,
    'header': 'X-Username: ' + 'a-' * 4000,
    'keys': 'token-' * 1333,
    'scheme': 'a+' * 4000,
    'jwt': 'eyJ-' * 2000,
    'slashes': '/' * 8000,
    'segments': 'a/' * 4000,
}


@pytest.mark.parametrize('formatter', [JsonFormatter, TextFormatter])
@pytest.mark.parametrize('name', ['ZenysisLogger', 'gunicorn.error'])
@pytest.mark.parametrize('text', _HOSTILE.values(), ids=_HOSTILE.keys())
def test_formatting_is_linear_in_hostile_messages(formatter, name, text):
    record = _record('Error handling request %s', (text,), logging.WARNING, name)
    start = time.perf_counter()
    formatter().format(record)
    assert time.perf_counter() - start < 0.2


@pytest.mark.parametrize('formatter', [JsonFormatter, TextFormatter])
@pytest.mark.parametrize('text', _HOSTILE.values(), ids=_HOSTILE.keys())
def test_formatting_is_linear_in_hostile_access_paths(formatter, text):
    record = _record('%(U)s', (), logging.INFO, 'gunicorn.access')
    record.args = {'m': 'GET', 'U': '/' + text, 's': '404', 'B': '0', 'D': '1'}
    start = time.perf_counter()
    formatter().format(record)
    assert time.perf_counter() - start < 0.2
