'''The renderer's only way out: a proxy to the map origins (SEC-10).

Run as its own service: `python -m harmony.worker.renderer.egress_proxy`. It sits
on the internal render network and on a network with a route out, so the
renderer keeps none of its own. Chromium sends every connection that is not to
the dashboard origin here. A CONNECT to an allowed https origin is tunnelled, and
a plain GET or HEAD from an allowed http origin is relayed without cookies or
credentials, one request per connection. Everything else is refused before any
connection is made.
'''

import json
import logging
import os
import selectors
import socket
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlsplit

from harmony.worker.renderer.egress import origin_of, parse_origins

LOG = logging.getLogger('harmony.worker.renderer.egress')

CONNECT_TIMEOUT_SECONDS = 10.0
# A tunnel or response with no bytes either way for this long is closed.
IDLE_TIMEOUT_SECONDS = 60.0
# Never relayed upstream: hop-by-hop headers, and anything that could carry a
# user's credentials to a third party.
DROPPED_HEADERS = {
    'connection',
    'keep-alive',
    'proxy-connection',
    'proxy-authorization',
    'te',
    'trailer',
    'upgrade',
    'host',
    'cookie',
    'authorization',
}

# Replaced with `Connection: close` in a relayed response, so the client never
# sends a second request on the connection.
HOP_BY_HOP_RESPONSE_HEADERS = {b'connection', b'keep-alive', b'proxy-connection'}
MAX_RESPONSE_HEAD_BYTES = 64 * 1024

Origin = tuple[str, str, int]


@dataclass(frozen=True)
class EgressProxySettings:
    allowed_origins: tuple[str, ...]
    port: int


def _relay(client: socket.socket, upstream: socket.socket) -> None:
    '''Copies bytes both ways until either side closes or both go idle.'''
    with selectors.DefaultSelector() as selector:
        selector.register(client, selectors.EVENT_READ, upstream)
        selector.register(upstream, selectors.EVENT_READ, client)
        while True:
            ready = selector.select(IDLE_TIMEOUT_SECONDS)
            if not ready:
                return
            for key, _ in ready:
                data = key.fileobj.recv(65536)  # type: ignore[union-attr]
                if not data:
                    return
                key.data.sendall(data)


def _with_connection_close(head: bytes) -> bytes:
    '''A response head whose connection headers say `Connection: close`.'''
    lines = head.split(b'\r\n')
    kept = [
        line
        for line in lines[1:]
        if line.split(b':', 1)[0].strip().lower() not in HOP_BY_HOP_RESPONSE_HEADERS
    ]
    return b'\r\n'.join([lines[0], *kept, b'Connection: close'])


def _relay_one_response(client: socket.socket, upstream: socket.socket) -> None:
    '''Copies the upstream's answer to the client, telling the client to close.

    Nothing more from the client is relayed: a later request on a kept-alive
    connection would reach the map origin with its headers unfiltered. Any byte
    or close from the client ends the relay.
    '''
    pending = b''
    head_sent = False
    with selectors.DefaultSelector() as selector:
        selector.register(client, selectors.EVENT_READ)
        selector.register(upstream, selectors.EVENT_READ)
        while True:
            ready = selector.select(IDLE_TIMEOUT_SECONDS)
            if not ready:
                return
            for key, _ in ready:
                if key.fileobj is client:
                    return
                data = upstream.recv(65536)
                if not data:
                    if pending:
                        client.sendall(pending)
                    return
                if head_sent:
                    client.sendall(data)
                    continue
                pending += data
                head, separator, body = pending.partition(b'\r\n\r\n')
                if separator:
                    client.sendall(_with_connection_close(head) + separator + body)
                    head_sent = True
                elif len(pending) > MAX_RESPONSE_HEAD_BYTES:
                    return


def _connect_origin(target: str) -> Optional[Origin]:
    '''The https origin a CONNECT `host:port` target names, else None.'''
    parts = urlsplit(f'//{target}')
    try:
        port = parts.port
    except ValueError:
        return None
    if not parts.hostname or port is None or parts.username is not None:
        return None
    return 'https', parts.hostname, port


def _fetch_origin(url: str) -> Optional[Origin]:
    '''The http origin an absolute-form GET names, else None (https uses CONNECT).'''
    origin = origin_of(url)
    return origin if origin is not None and origin[0] == 'http' else None


def build_proxy(settings: EgressProxySettings) -> ThreadingHTTPServer:
    allowed = {origin_of(origin) for origin in settings.allowed_origins}

    class Handler(BaseHTTPRequestHandler):
        server_version = 'harmony-render-egress'
        sys_version = ''

        def _decide(self, origin: Optional[Origin]) -> bool:
            '''Logs the decision and refuses a disallowed request.'''
            is_allowed = origin is not None and origin in allowed
            if origin is not None:
                _, host, port = origin
                entry = {'event': 'egress', 'host': host, 'port': port}
                LOG.info(json.dumps({**entry, 'allowed': is_allowed}))
            if not is_allowed:
                self._refuse(403)
            return is_allowed

        def _refuse(self, status: int) -> None:
            self.close_connection = True
            self.send_response(status)
            self.send_header('Content-Length', '0')
            self.send_header('Connection', 'close')
            self.end_headers()

        def _connect(self, origin: Origin) -> Optional[socket.socket]:
            _, host, port = origin
            try:
                return socket.create_connection(
                    (host, port), timeout=CONNECT_TIMEOUT_SECONDS
                )
            except OSError:
                self._refuse(502)
                return None

        def do_CONNECT(self) -> None:  # noqa: N802
            origin = _connect_origin(self.path)
            if origin is None or not self._decide(origin):
                if origin is None:
                    self._refuse(403)
                return
            upstream = self._connect(origin)
            if upstream is None:
                return
            with upstream:
                self.send_response(200, 'Connection Established')
                self.end_headers()
                self.close_connection = True
                _relay(self.connection, upstream)

        def _fetch(self) -> None:
            parts = urlsplit(self.path)
            has_body = self.headers.get('Content-Length', '0') != '0' or bool(
                self.headers.get('Transfer-Encoding')
            )
            if not parts.scheme or has_body:
                # Chromium sends a proxy only absolute-form requests, and map
                # fetches carry no body.
                self._refuse(400)
                return
            origin = _fetch_origin(self.path)
            if origin is None or not self._decide(origin):
                if origin is None:
                    self._refuse(403)
                return
            target = (parts.path or '/') + (f'?{parts.query}' if parts.query else '')
            head = [f'{self.command} {target} HTTP/1.1', f'Host: {parts.netloc}']
            head += [
                f'{name}: {value}'
                for name, value in self.headers.items()
                if name.lower() not in DROPPED_HEADERS
            ]
            head.append('Connection: close')
            upstream = self._connect(origin)
            if upstream is None:
                return
            with upstream:
                upstream.sendall(('\r\n'.join(head) + '\r\n\r\n').encode('latin-1'))
                self.close_connection = True
                _relay_one_response(self.connection, upstream)

        do_GET = _fetch  # noqa: N815
        do_HEAD = _fetch  # noqa: N815

        def _not_a_fetch(self) -> None:
            self._refuse(405)

        do_POST = _not_a_fetch  # noqa: N815
        do_PUT = _not_a_fetch  # noqa: N815
        do_PATCH = _not_a_fetch  # noqa: N815
        do_DELETE = _not_a_fetch  # noqa: N815
        do_OPTIONS = _not_a_fetch  # noqa: N815

        def log_message(self, format: str, *args: Any) -> None:  # pylint: disable=redefined-builtin
            # One JSON line per decision instead: request lines carry map access
            # tokens in their query strings.
            return

    # Only reachable on the internal render network (Compose).
    server = ThreadingHTTPServer(('0.0.0.0', settings.port), Handler)  # noqa: S104
    server.daemon_threads = True
    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    settings = EgressProxySettings(
        allowed_origins=parse_origins(os.environ.get('EGRESS_ALLOWED_ORIGINS', '')),
        port=int(os.environ.get('EGRESS_PROXY_PORT', '3128')),
    )
    LOG.info(
        json.dumps(
            {
                'event': 'start',
                'port': settings.port,
                'allowed_origins': list(settings.allowed_origins),
            }
        )
    )
    build_proxy(settings).serve_forever()


if __name__ == '__main__':
    main()
