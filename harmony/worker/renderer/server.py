'''The renderer's HTTP surface: `POST /render` and `GET /healthz`.

The browser work is a `render(spec, settings)` callable, so the HTTP layer can be
tested without Chromium.
'''

import dataclasses
import itertools
import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, NamedTuple, Optional

from harmony.worker.renderer.errors import OutputTooLarge, RenderError
from harmony.worker.renderer.spec import RenderSpec, parse_render_request

LOG = logging.getLogger('harmony.worker.renderer')

MAX_BODY_BYTES = 16 * 1024
CONTENT_TYPES = {'pdf': 'application/pdf', 'png': 'image/png', 'jpeg': 'image/jpeg'}


@dataclass(frozen=True)
class RendererSettings:
    allowed_origin: str
    port: int
    max_timeout_seconds: float
    max_bytes: int
    concurrency: int
    max_page_height: int
    # Map style and tile origins the page may fetch (never navigate to), only
    # through `egress_proxy`. Without a proxy nothing but the dashboard origin
    # is reachable.
    map_origins: tuple[str, ...] = ()
    egress_proxy: Optional[str] = None
    # Once the page needed something it could not get, how long it still has
    # to signal ready before the render fails instead of waiting out its
    # deadline. Refusing a host listed in `ignored_blocked_hosts` (telemetry)
    # does not start this.
    blocked_grace_seconds: float = 10.0
    ignored_blocked_hosts: tuple[str, ...] = ('events.mapbox.com',)
    # How long a render may overrun its deadline while its browser closes. Its
    # process and everything it started are killed after that.
    cleanup_grace_seconds: float = 10.0


@dataclass(frozen=True)
class RenderOutput:
    content: bytes
    # Hosts the page tried to reach and the egress guard refused (for WP-7g).
    blocked_hosts: tuple[str, ...]


Render = Callable[[RenderSpec, RendererSettings], RenderOutput]


class Reply(NamedTuple):
    status: int
    content_type: str
    body: bytes
    headers: dict[str, str]


class Busy(RenderError):
    status = 503
    code = 'busy'


class Slots:
    '''The render slots, and when each held one must be free again.

    A render that overruns its deadline is killed after the clean-up grace
    (`isolation.run_isolated`). A slot still held one more grace period later
    means that kill failed, and only a restart can recover it.
    '''

    def __init__(self, count: int, cleanup_grace_seconds: float) -> None:
        self._free = threading.BoundedSemaphore(count)
        self._grace = cleanup_grace_seconds
        self._lock = threading.Lock()
        self._free_by: dict[int, float] = {}
        self._ids = itertools.count()

    @contextmanager
    def hold(self, timeout_seconds: float) -> Iterator[float]:
        '''Holds a slot for a render due within `timeout_seconds`, yielding the
        time left once the slot is held. Raises Busy without a slot in time.
        '''
        deadline = time.monotonic() + timeout_seconds
        if not self._free.acquire(timeout=timeout_seconds):
            raise Busy('no render slot before the deadline')
        slot = next(self._ids)
        with self._lock:
            self._free_by[slot] = deadline + 2 * self._grace
        try:
            yield max(deadline - time.monotonic(), 0.001)
        finally:
            with self._lock:
                del self._free_by[slot]
            self._free.release()

    def stuck(self) -> bool:
        now = time.monotonic()
        with self._lock:
            return any(free_by < now for free_by in self._free_by.values())


class RendererServer(ThreadingHTTPServer):
    slots: Slots


def watch(
    server: RendererServer, give_up: Callable[[], None], interval: float = 1.0
) -> None:
    '''Calls `give_up` once a render slot is stuck (see `Slots`). The service
    exits there, so Docker restarts it and the stuck browser goes with it.'''
    while not server.slots.stuck():
        time.sleep(interval)
    LOG.error(json.dumps({'event': 'stuck', 'error': 'a render slot was never freed'}))
    give_up()


def build_server(settings: RendererSettings, render: Render) -> RendererServer:
    slots = Slots(settings.concurrency, settings.cleanup_grace_seconds)

    def run(spec: RenderSpec) -> RenderOutput:
        with slots.hold(spec.timeout_seconds) as remaining:
            output = render(
                dataclasses.replace(spec, timeout_seconds=remaining), settings
            )
        if len(output.content) > settings.max_bytes:
            raise OutputTooLarge(f'{len(output.content)} bytes')
        return output

    class Handler(BaseHTTPRequestHandler):
        server_version = 'harmony-renderer'
        sys_version = ''

        def do_GET(self) -> None:  # noqa: N802
            if self.path == '/healthz':
                if slots.stuck():
                    self._send_error(503, 'stuck')
                else:
                    self._send(200, 'text/plain', b'ok')
            elif self.path == '/render':
                self._send_error(405, 'method_not_allowed')
            else:
                self._send_error(404, 'not_found')

        def do_POST(self) -> None:  # noqa: N802
            if self.path == '/healthz':
                self._send_error(405, 'method_not_allowed')
                return
            if self.path != '/render':
                self._send_error(404, 'not_found')
                return
            started = time.monotonic()
            entry: dict[str, Any] = {'event': 'render'}
            reply = self._render(entry)
            entry['duration_ms'] = int((time.monotonic() - started) * 1000)
            entry['status'] = reply.status
            reply.headers['Server-Timing'] = f'render;dur={entry["duration_ms"]}'
            LOG.info(json.dumps(entry))
            self._send(reply.status, reply.content_type, reply.body, reply.headers)

        def _render(self, entry: dict[str, Any]) -> Reply:
            length = self.headers.get('Content-Length')
            if length is None or not (length.isascii() and length.isdecimal()):
                self.close_connection = True
                return self._error(411, 'length_required', entry)
            if int(length) > MAX_BODY_BYTES:
                self.close_connection = True
                return self._error(413, 'body_too_large', entry)
            body = self.rfile.read(int(length))
            try:
                spec = parse_render_request(
                    body,
                    allowed_origin=settings.allowed_origin,
                    max_timeout_seconds=settings.max_timeout_seconds,
                )
                entry['format'] = spec.format
                output = run(spec)
            except RenderError as error:
                entry['reason'] = str(error)
                return self._error(error.status, error.code, entry)
            except Exception as error:  # pylint: disable=broad-except
                # Only the type: a browser error's text can quote the request.
                entry['reason'] = type(error).__name__
                return self._error(500, 'internal', entry)
            entry['bytes'] = len(output.content)
            entry['blocked_hosts'] = sorted(output.blocked_hosts)
            return Reply(200, CONTENT_TYPES[spec.format], output.content, {})

        @staticmethod
        def _error(status: int, code: str, entry: dict[str, Any]) -> Reply:
            entry['error'] = code
            body = json.dumps({'error': code}).encode()
            return Reply(status, 'application/json', body, {})

        def _send_error(self, status: int, code: str) -> None:
            self._send(status, 'application/json', json.dumps({'error': code}).encode())

        def _send(
            self,
            status: int,
            content_type: str,
            body: bytes,
            extra: Optional[dict[str, str]] = None,
        ) -> None:
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # pylint: disable=redefined-builtin
            # One JSON line per render is logged instead of the access log.
            return

    # Only reachable on the internal render network (Compose).
    server = RendererServer(('0.0.0.0', settings.port), Handler)  # noqa: S104
    server.daemon_threads = True
    server.slots = slots
    return server
