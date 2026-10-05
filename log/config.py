'''One logging configuration for the web app, the Celery worker, gunicorn and the
pipeline: every record goes to a single stream handler on the root logger.

Environment:
    LOG_FORMAT  `json` (one JSON object per line) or `text` (for people). Unset means
                `json` when ZEN_PROD is set and `text` otherwise. The web image
                (which also runs the worker) sets ZEN_PROD; the pipeline image does
                not. The Compose files set LOG_FORMAT for each service anyway.
    LOG_STREAM  `stdout` or `stderr`, default `stderr`. Pipeline steps read other
                scripts' stdout (`SOURCES=($(generate_pipeline_sources.py ...))`), so
                only long-running services, whose stdout carries no data, use stdout.
    LOG_LEVEL   Root level, default INFO. The old production config logged
                ZenysisLogger at DEBUG; set LOG_LEVEL=DEBUG to get those lines.
                DEBUG also applies to every library that leaves its own logger's
                level unset (urllib3 and kombu among them), whose debug lines can
                carry URLs with query strings and message payloads that redaction
                does not catch. Use it briefly, not as a production setting.
    ZEN_ENV     Written as `deployment` on JSON lines.

Every line passes through `redact` first. That is a backstop for secrets that reach
a log call by mistake, not a licence to log them.
'''

from __future__ import annotations

import base64
import binascii
import json
import logging
import logging.config
import os
import re
import sys
import threading
from datetime import datetime, timezone
from types import TracebackType
from typing import (
    Any,
    Callable,
    Dict,
    Mapping,
    Match,
    Optional,
    Pattern,
    Tuple,
    Type,
    Union,
)

from log import context

TEXT_FORMAT = (
    '%(asctime)s.%(msecs)03d %(levelname)s %(filename)s:%(funcName)s:%(lineno)d: '
    '%(message)s'
)
TEXT_DATE_FORMAT = '%Y%m%d.%H%M%S'

REDACTED = '[REDACTED]'

# Log lines carry client-controlled text, so every pattern must run in linear time.
# A pattern that may start anywhere inside a long run and scan to its end is
# quadratic. So each pattern starts at a literal that cannot repeat inside the run
# it scans (`://`, `.eyJ`), or only at the start of a run (a lookbehind), or scans a
# bounded span. The key pattern scans its run once: Python never backtracks into a
# lookahead, and the backreference re-matches what the lookahead captured.
_SENSITIVE_WORD = (
    r'(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key'
    r'|authorization)'
)
# A whole run of word characters and hyphens that names a secret.
_SENSITIVE_KEY = r'(?<![\w-])(?=[\w-]*?' + _SENSITIVE_WORD + r')(?=([\w-]+))\2'
# key=value, key: value, 'key': 'value' and the header tuple ('key', 'value').
_SEPARATOR = r'(?:["\']?\s*[:=]|["\']\s*,)\s*'
# A quoted value runs to its closing quote; `b` prefixes a bytes literal.
_QUOTED = r'b?"(?:[^"\\\r\n]|\\.)*|b?\'(?:[^\'\\\r\n]|\\.)*'
_OPENING_QUOTE = re.compile(r'b?["\']', re.IGNORECASE)
# The value after a separator, unless an earlier pattern already redacted it.
_VALUE = (
    r'(?!b?["\']?\[REDACTED\])(?P<value>' + _QUOTED + r'|'
    r'(?:(?i:bearer|basic|digest|token)\s+)?[^\s"\',;&)}\]]+)'
)


def _redact_value(match: Match[str]) -> str:
    opening = _OPENING_QUOTE.match(match.group('value'))
    return match.group(1) + (opening.group() if opening else '') + REDACTED


def _redact_basic_credentials(match: Match[str]) -> str:
    '''Redact a Basic value only when it decodes to user:password, so prose like
    "Basic auth is disabled" stays readable.'''
    try:
        decoded = base64.b64decode(match.group(2), validate=True)
    except binascii.Error:
        return match.group()
    return match.group(1) + REDACTED if b':' in decoded else match.group()


_REDACTIONS: Tuple[
    Tuple[Pattern[str], Union[str, Callable[[Match[str]], str]]], ...
] = (
    # scheme://user:password@host, whatever the scheme is glued to.
    (re.compile(r'(://[^\s/:@]*:)[^\s/@]+@'), r'\1' + REDACTED + '@'),
    (
        re.compile(r'(?i)(["\']?' + _SENSITIVE_KEY + _SEPARATOR + r')' + _VALUE),
        _redact_value,
    ),
    # Cookie headers in any form, including the WSGI environ's HTTP_COOKIE.
    (
        re.compile(
            r'(?i)(?<![a-z0-9])((?:set-)?cookie' + _SEPARATOR + r'b?["\']?)'
            r'[^\r\n"\']+'
        ),
        r'\1' + REDACTED,
    ),
    # Flask's session cookie outside a Cookie header: session=..., a quoted dict or
    # JSON key, or a (name, value) tuple. An unquoted `session:` is prose. The app's
    # other cookies (accessKey, remember_token, csrf_access_token) name a key or
    # token, so the key pattern above already redacts them.
    (re.compile(r'\bsession=[^;\s&"\']+'), 'session=' + REDACTED),
    (re.compile(r'(["\']session["\']\s*[:,]\s*)' + _VALUE), _redact_value),
    (
        re.compile(r'(?i)\b(bearer\s+)(?!\[REDACTED\])[A-Za-z0-9._~+/=-]+'),
        r'\1' + REDACTED,
    ),
    (
        re.compile(r'(?i)(?<![\w-])(basic\s+)([A-Za-z0-9+/]+={0,2})'),
        _redact_basic_credentials,
    ),
    # A JWT's payload and signature; its header names only the algorithm.
    # After a dot (x.<jwt>) the match starts at the header, so allow a third part.
    (
        re.compile(r'\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]*)?'),
        '.' + REDACTED,
    ),
    # Flask-User's reset and confirmation links carry the token in the path.
    (
        re.compile(r'(?i)(/(?:reset[-_]password|confirm[-_]email)/)[^\s/?"\']+'),
        r'\1' + REDACTED,
    ),
    # gunicorn's body-parsing errors repeat the request body bytes they choked on,
    # in its own lines and in app tracebacks alike. InvalidChunkSize is raised from
    # int(size, 16), whose ValueError is chained into the same traceback.
    (
        re.compile(
            r'(No more data after|Invalid chunk size|Invalid chunk terminator[^:\n]{0,32}'
            r'|invalid literal for int\(\) with base 16): [^\n]+'
        ),
        r'\1: ' + REDACTED,
    ),
)

# gunicorn logs client-supplied URIs ("Error handling request /path?query"), and a
# query string can carry any secret, not only the named ones above. A match starts
# only at the start of a token, and the token holds a path before the `?`.
_QUERY_STRING = re.compile(r'(?<![^\s\'"])([^\s?\'"/]*/[^\s?\'"]*)\?[^\s\'"]+')

_FORMATS = ('json', 'text')
_STREAMS = ('stdout', 'stderr')


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def _redact_request_uris(record: logging.LogRecord, text: str) -> str:
    if record.name.startswith('gunicorn.'):
        return _QUERY_STRING.sub(r'\1?' + REDACTED, text)
    return text


def _context_fields(record: logging.LogRecord) -> Dict[str, Any]:
    fields: Dict[str, Any] = dict(context.bound_fields())
    if 'request_id' not in fields:
        # Lines written through a LoggerAdapter that carries its own request id.
        adapter_request_id = getattr(record, 'request_id', None)
        if adapter_request_id is not None:
            fields['request_id'] = str(adapter_request_id)
    user_id = context.current_user_id()
    if user_id is not None:
        fields['user_id'] = user_id
    return fields


def _gunicorn_access_fields(atoms: Mapping[str, Any]) -> Dict[str, Any]:
    '''Fields of a gunicorn access record, whose args are gunicorn's atoms.

    The query string is left out: it can carry tokens.
    '''

    def number(key: str) -> int:
        value = atoms.get(key, '-')
        return int(value) if str(value).isdigit() else 0

    return {
        'method': atoms.get('m', '-'),
        'path': redact(str(atoms.get('U', '-'))),
        'status': number('s'),
        'bytes': number('B'),
        'duration_s': round(number('D') / 1_000_000, 6),
    }


def _gunicorn_access(
    record: logging.LogRecord,
) -> Optional[Tuple[str, Dict[str, Any], Optional[str]]]:
    '''Message, http fields and response request id of a gunicorn access record.

    Both formats build the line from these instead of gunicorn's access format,
    whose request line, referer and user atoms carry query strings and credentials.
    '''
    if record.name != 'gunicorn.access' or not isinstance(record.args, Mapping):
        return None
    http = _gunicorn_access_fields(record.args)
    message = f"{http['method']} {http['path']} {http['status']}"
    request_id = record.args.get('{x-request-id}o', '-')
    return message, http, None if request_id == '-' else str(request_id)


class JsonFormatter(logging.Formatter):
    def __init__(self, deployment: Optional[str] = None) -> None:
        super().__init__()
        self.deployment = (
            deployment if deployment is not None else os.environ.get('ZEN_ENV')
        )

    def formatException(self, ei: Any) -> str:
        return redact(super().formatException(ei))

    def formatStack(self, stack_info: str) -> str:
        return redact(super().formatStack(stack_info))

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, timezone.utc)
        entry: Dict[str, Any] = {
            'timestamp': timestamp.isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'logger': record.name,
        }
        access = _gunicorn_access(record)
        if access is None:
            http = None
            response_request_id = None
            message = redact(record.getMessage())
            entry['message'] = _redact_request_uris(record, message)
        else:
            entry['message'], http, response_request_id = access
        entry['source'] = f'{record.filename}:{record.funcName}:{record.lineno}'
        if self.deployment:
            entry['deployment'] = self.deployment
        entry.update(_context_fields(record))
        if response_request_id is not None:
            entry.setdefault('request_id', response_request_id)
        if http is not None:
            entry['http'] = http
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            entry['exc_info'] = _redact_request_uris(record, exc_text)
        elif record.exc_text:
            exc_text = redact(record.exc_text)
            entry['exc_info'] = _redact_request_uris(record, exc_text)
        if record.stack_info:
            entry['stack_info'] = self.formatStack(record.stack_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(TEXT_FORMAT, TEXT_DATE_FORMAT)

    def formatException(self, ei: Any) -> str:
        return redact(super().formatException(ei))

    def formatStack(self, stack_info: str) -> str:
        return redact(super().formatStack(stack_info))

    def format(self, record: logging.LogRecord) -> str:
        return _redact_request_uris(record, super().format(record))

    def formatMessage(self, record: logging.LogRecord) -> str:
        message = record.message
        fields = _context_fields(record)
        access = _gunicorn_access(record)
        if access is None:
            text = redact(message)
        else:
            text, http, response_request_id = access
            if response_request_id is not None:
                fields.setdefault('request_id', response_request_id)
            fields.update(bytes=http['bytes'], duration_s=http['duration_s'])
        suffix = ' '.join(f'{name}={value}' for name, value in fields.items())
        record.message = f'{text} [{suffix}]' if suffix else text
        try:
            return super().formatMessage(record)
        finally:
            record.message = message


def _choice(variable: str, choices: Tuple[str, ...], default: str) -> str:
    value = os.environ.get(variable, '').strip().lower() or default
    if value not in choices:
        raise ValueError(
            f'{variable} must be one of {", ".join(choices)}, not {value!r}'
        )
    return value


def _format_class() -> Type[logging.Formatter]:
    default = 'json' if os.environ.get('ZEN_PROD') else 'text'
    if _choice('LOG_FORMAT', _FORMATS, default) == 'json':
        return JsonFormatter
    return TextFormatter


def logging_config() -> Dict[str, Any]:
    '''A dictConfig for this process, from the environment.

    gunicorn takes it as `logconfig_dict`, so gunicorn's own loggers get the same
    handler. That setting is also what turns gunicorn's access lines on.
    '''
    level = os.environ.get('LOG_LEVEL', 'INFO').strip().upper() or 'INFO'
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {'default': {'()': _format_class()}},
        'handlers': {
            'stream': {
                'class': 'logging.StreamHandler',
                'formatter': 'default',
                'stream': f'ext://sys.{_choice("LOG_STREAM", _STREAMS, "stderr")}',
            }
        },
        'root': {'level': level, 'handlers': ['stream']},
        'loggers': {
            # Named so a reconfiguration (gunicorn applies this dict after adding
            # its own handlers) strips their handlers and they propagate to root.
            'ZenysisLogger': {'propagate': True},
            'gunicorn.error': {'propagate': True},
            'gunicorn.access': {'level': 'INFO', 'propagate': True},
        },
    }


def _log_uncaught(
    exc_type: Type[BaseException],
    exc: BaseException,
    traceback: Optional[TracebackType],
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, traceback)
        return
    logging.getLogger('uncaught').error(
        'Uncaught %s: %s', exc_type.__name__, exc, exc_info=(exc_type, exc, traceback)
    )


def _log_uncaught_in_thread(args: Any) -> None:
    if args.exc_value is not None:
        _log_uncaught(args.exc_type, args.exc_value, args.exc_traceback)


def configure_logging() -> None:
    '''Apply `logging_config()`, and route warnings and uncaught exceptions to it.'''
    logging.config.dictConfig(logging_config())
    logging.captureWarnings(True)
    sys.excepthook = _log_uncaught
    threading.excepthook = _log_uncaught_in_thread
