'''Celery logging: keep this package's configuration in the worker, and carry the
request id from the web request that published a task to the task's log lines.
'''

from __future__ import annotations

from typing import Any, Dict, Optional

from celery import signals

from log import context

_HEADER = 'request_id'
_CONTEXT_RESET_ATTRIBUTE = '_log_context_token'


def connect_celery_logging() -> None:
    for signal, receiver in (
        (signals.setup_logging, _keep_logging_config),
        (signals.before_task_publish, _add_request_id_header),
        (signals.task_prerun, _bind_task_context),
        (signals.task_postrun, _reset_task_context),
    ):
        signal.connect(receiver, weak=False, dispatch_uid=__name__)


def _keep_logging_config(**_kwargs: Any) -> None:
    '''Connected only so Celery leaves the root logger alone.

    Logging was configured when `log` was imported. With no receiver for this
    signal, Celery replaces the root handlers with its own and redirects stdout.
    The worker's `--loglevel` is therefore ignored; LOG_LEVEL applies.
    '''


def _add_request_id_header(
    headers: Optional[Dict[str, Any]] = None, **_kwargs: Any
) -> None:
    request_id = context.current_request_id()
    if headers is not None and request_id is not None:
        headers[_HEADER] = request_id


def _bind_task_context(task_id: str, task: Any, **_kwargs: Any) -> None:
    fields = {'task': task.name, 'task_id': task_id}
    request_id = task.request.get(_HEADER)
    # An eager task runs in the caller's context and already has its request id.
    if context.is_well_formed_request_id(request_id):
        fields['request_id'] = request_id
    setattr(task.request, _CONTEXT_RESET_ATTRIBUTE, context.bind(**fields))


def _reset_task_context(task: Any, **_kwargs: Any) -> None:
    token = getattr(task.request, _CONTEXT_RESET_ATTRIBUTE, None)
    if token is not None:
        context.reset(token)
