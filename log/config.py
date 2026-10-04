'''One logging configuration for the web app, the Celery worker, gunicorn and the
pipeline: every record goes to a single stream handler on the root logger.

Environment:
    LOG_FORMAT  `json` (one JSON object per line) or `text` (for people). Unset means
                `json` when ZEN_PROD is set, as in the web image, and `text` otherwise.
    LOG_STREAM  `stdout` or `stderr`, default `stderr`. Pipeline steps read other
                scripts' stdout (`SOURCES=($(generate_pipeline_sources.py ...))`), so
                only long-running services, whose stdout carries no data, use stdout.
    LOG_LEVEL   Root level, default INFO.
    ZEN_ENV     Written as `deployment` on JSON lines.

Every line passes through `redact` first. That is a backstop for secrets that reach
a log call by mistake, not a licence to log them.
'''

from __future__ import annotations

import json
import logging
import logging.config
import os
import re
import sys
import threading
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Dict, Mapping, Optional, Tuple, Type

from log import context

TEXT_FORMAT = (
    '%(asctime)s.%(msecs)03d %(levelname)s %(filename)s:%(funcName)s:%(lineno)d: '
    '%(message)s'
)
TEXT_DATE_FORMAT = '%Y%m%d.%H%M%S'

REDACTED = '[REDACTED]'

_SECRET_KEY = (
    r'[\w-]*?(?:password|passwd|secret|token|api[_-]?key|access[_-]?key'
    r'|private[_-]?key|authorization)[\w-]*'
)
_REDACTIONS = (
    # scheme://user:password@host
    (
        re.compile(r'([a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@]*:)[^\s/@]+@'),
        r'\1' + REDACTED + '@',
    ),
    # key=value, key: value, 'key': 'value' and "key": "Basic value"
    (
        re.compile(
            r'(?i)(["\']?\b' + _SECRET_KEY + r'["\']?\s*[:=]\s*["\']?)'
            r'(?:(?:bearer|basic|digest|token)\s+)?(?!\[REDACTED\])[^\s"\',;&)}\]]+'
        ),
        r'\1' + REDACTED,
    ),
    (
        re.compile(r'(?i)\b((?:set-)?cookie["\']?\s*[:=]\s*["\']?)[^\r\n"\']+'),
        r'\1' + REDACTED,
    ),
    (
        re.compile(
            r'\b(accessKey|session|remember_token|csrf_access_token)=[^;\s&"\']+'
        ),
        r'\1=' + REDACTED,
    ),
    (
        re.compile(r'(?i)\b(bearer\s+)(?!\[REDACTED\])[A-Za-z0-9._~+/=-]+'),
        r'\1' + REDACTED,
    ),
    (re.compile(r'\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*'), REDACTED),
    # Flask-User's reset and confirmation links carry the token in the path.
    (
        re.compile(r'(?i)(/(?:reset[-_]password|confirm[-_]email)/)[^\s/?"\']+'),
        r'\1' + REDACTED,
    ),
)

_FORMATS = ('json', 'text')
_STREAMS = ('stdout', 'stderr')


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
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
        if record.name == 'gunicorn.access' and isinstance(record.args, Mapping):
            http = _gunicorn_access_fields(record.args)
            entry['message'] = f"{http['method']} {http['path']} {http['status']}"
            response_request_id = record.args.get('{x-request-id}o', '-')
        else:
            http = None
            entry['message'] = redact(record.getMessage())
            response_request_id = '-'
        entry['source'] = f'{record.filename}:{record.funcName}:{record.lineno}'
        if self.deployment:
            entry['deployment'] = self.deployment
        entry.update(_context_fields(record))
        if response_request_id != '-':
            entry.setdefault('request_id', response_request_id)
        if http is not None:
            entry['http'] = http
        if record.exc_info:
            entry['exc_info'] = self.formatException(record.exc_info)
        elif record.exc_text:
            entry['exc_info'] = redact(record.exc_text)
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

    def formatMessage(self, record: logging.LogRecord) -> str:
        message = record.message
        fields = _context_fields(record)
        suffix = ' '.join(f'{name}={value}' for name, value in fields.items())
        record.message = f'{redact(message)} [{suffix}]' if suffix else redact(message)
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
    '''Apply `logging_config()` and log uncaught exceptions through it.'''
    logging.config.dictConfig(logging_config())
    sys.excepthook = _log_uncaught
    threading.excepthook = _log_uncaught_in_thread
