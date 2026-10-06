'''WSGI middleware that gives every request an id, binds it for the request's log
lines and echoes it in the `X-Request-ID` response header.
'''

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from log import context

Environ = Dict[str, Any]
StartResponse = Callable[..., Any]
WsgiApp = Callable[[Environ, StartResponse], Iterable[bytes]]

_ENVIRON_KEY = 'HTTP_' + context.REQUEST_ID_HEADER.upper().replace('-', '_')


class RequestIdMiddleware:
    def __init__(self, app: WsgiApp) -> None:
        self.app = app

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        request_id = context.accept_request_id(environ.get(_ENVIRON_KEY))
        environ[_ENVIRON_KEY] = request_id

        def start_with_request_id(
            status: str,
            headers: List[Tuple[str, str]],
            exc_info: Optional[Any] = None,
        ) -> Any:
            headers = [
                (name, value)
                for name, value in headers
                if name.lower() != context.REQUEST_ID_HEADER.lower()
            ]
            headers.append((context.REQUEST_ID_HEADER, request_id))
            return start_response(status, headers, exc_info)

        # Flask runs the view and its teardown inside this call, so every app log
        # line is bound. Lines written while a streamed body is iterated are not;
        # wrapping the body would cost gunicorn its sendfile path for file responses.
        token = context.bind(request_id=request_id)
        try:
            return self.app(environ, start_with_request_id)
        finally:
            context.reset(token)
