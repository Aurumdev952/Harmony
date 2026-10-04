'''Request logging for the Flask app: request ids and the signed-in user's id.'''

from __future__ import annotations

from typing import Any, Optional

from log import context
from log.request_id import RequestIdMiddleware


def install_request_logging(app: Any) -> None:
    app.wsgi_app = RequestIdMiddleware(app.wsgi_app)
    context.set_user_id_provider(_loaded_user_id)


def _loaded_user_id() -> Optional[context.UserId]:
    # pylint: disable=import-outside-toplevel
    from flask import _request_ctx_stack, has_request_context

    if not has_request_context():
        return None
    # Only a user Flask-Login has already loaded, read from the instance dict: a log
    # call must never run the user loader or refresh an expired SQLAlchemy row.
    user = getattr(_request_ctx_stack.top, 'user', None)
    user_id = getattr(user, '__dict__', {}).get('id')
    return user_id if isinstance(user_id, (int, str)) else None
