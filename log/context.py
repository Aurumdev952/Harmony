'''Fields added to every log line written while they are bound: the request id, and
the task name and id inside a Celery task.

They live in a ContextVar, so they are per thread, per greenlet under gevent and
per asyncio task. The user id is looked up when a line is written instead, because
a request's user is only known after authentication, well after its id is bound.
'''

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar, Token
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Union

REQUEST_ID_HEADER = 'X-Request-ID'

# Wide enough for uuids, nginx $request_id and most tracing ids; narrow enough that
# a client cannot inject spaces, quotes or newlines into log lines.
_WELL_FORMED_REQUEST_ID = re.compile(r'[A-Za-z0-9._:-]{1,128}')

UserId = Union[int, str]

_FIELDS: ContextVar[Mapping[str, str]] = ContextVar(
    'log_fields', default=MappingProxyType({})
)
_user_id_provider: Optional[Callable[[], Optional[UserId]]] = None


def new_request_id() -> str:
    return uuid.uuid4().hex


def is_well_formed_request_id(value: object) -> bool:
    return isinstance(value, str) and bool(_WELL_FORMED_REQUEST_ID.fullmatch(value))


def accept_request_id(value: Optional[str]) -> str:
    '''`value` when it is a well-formed request id, otherwise a new one.'''
    if value is not None and is_well_formed_request_id(value):
        return value
    return new_request_id()


def bind(**fields: str) -> Token[Mapping[str, str]]:
    return _FIELDS.set({**_FIELDS.get(), **fields})


def reset(token: Token[Mapping[str, str]]) -> None:
    _FIELDS.reset(token)


def bound_fields() -> Mapping[str, str]:
    return _FIELDS.get()


def current_request_id() -> Optional[str]:
    return _FIELDS.get().get('request_id')


def set_user_id_provider(provider: Optional[Callable[[], Optional[UserId]]]) -> None:
    '''Install the callable that returns the current user's id, or None.'''
    global _user_id_provider  # pylint: disable=global-statement
    _user_id_provider = provider


def current_user_id() -> Optional[UserId]:
    provider = _user_id_provider
    if provider is None:
        return None
    try:
        return provider()
    except Exception:  # pylint: disable=broad-except
        # A log call must never fail because the user could not be looked up.
        return None
