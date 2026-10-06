"""WP-1h: the egress proxy, the renderer's only way out (SEC-10).

It relays to the configured map origins and refuses everything else without
connecting. The upstreams here are local servers; nothing leaves the host.
"""

import json
import logging
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from harmony.worker.renderer.egress_proxy import EgressProxySettings, build_proxy


class Upstream:
    """A local TCP server that records what it receives and answers like HTTP."""

    def __init__(self) -> None:
        self.received: list[bytes] = []
        self.connections = 0
        self.server = socket.create_server(('127.0.0.1', 0))
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            self.connections += 1
            with connection:
                data = connection.recv(65536)
                self.received.append(data)
                connection.sendall(
                    b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\n'
                    b'Connection: close\r\n\r\nstyle'
                )

    def close(self) -> None:
        self.server.close()


@pytest.fixture(name='upstream')
def fixture_upstream() -> Iterator[Upstream]:
    upstream = Upstream()
    yield upstream
    upstream.close()


@contextmanager
def proxying(*allowed: str) -> Iterator[int]:
    server = build_proxy(EgressProxySettings(allowed_origins=allowed, port=0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def send(proxy_port: int, request: bytes) -> bytes:
    with socket.create_connection(('127.0.0.1', proxy_port), timeout=5) as client:
        client.sendall(request)
        chunks = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                return b''.join(chunks)
            chunks.append(chunk)


def status_of(response: bytes) -> int:
    return int(response.split(b' ', 2)[1])


def test_a_connect_to_an_allowed_https_origin_is_tunnelled(upstream):
    with proxying(f'https://127.0.0.1:{upstream.port}') as port:
        with socket.create_connection(('127.0.0.1', port), timeout=5) as client:
            client.sendall(
                f'CONNECT 127.0.0.1:{upstream.port} HTTP/1.1\r\n\r\n'.encode()
            )
            established = client.recv(65536)
            client.sendall(b'GET /styles HTTP/1.1\r\nHost: maps\r\n\r\n')
            relayed = b''
            while chunk := client.recv(65536):
                relayed += chunk

    assert status_of(established) == 200
    assert upstream.received == [b'GET /styles HTTP/1.1\r\nHost: maps\r\n\r\n']
    assert relayed.endswith(b'style')


@pytest.mark.parametrize(
    'target',
    [
        '127.0.0.1:{other}',  # another port on the allowed host
        'localhost:{port}',  # the same address under another name
        '169.254.169.254:443',
        '[::1]:{port}',
        '127.0.0.1',  # no port
    ],
)
def test_a_connect_anywhere_else_is_refused_without_connecting(upstream, target):
    other = Upstream()
    try:
        with proxying(f'https://127.0.0.1:{upstream.port}') as port:
            response = send(
                port,
                'CONNECT {} HTTP/1.1\r\n\r\n'.format(
                    target.format(port=upstream.port, other=other.port)
                ).encode(),
            )
    finally:
        other.close()

    assert status_of(response) == 403
    assert upstream.connections == 0
    assert other.connections == 0


def test_a_connect_to_an_origin_allowed_only_over_http_is_refused(upstream):
    with proxying(f'http://127.0.0.1:{upstream.port}') as port:
        response = send(
            port, f'CONNECT 127.0.0.1:{upstream.port} HTTP/1.1\r\n\r\n'.encode()
        )

    assert status_of(response) == 403
    assert upstream.connections == 0


def test_a_plain_http_fetch_from_an_allowed_origin_is_relayed_without_credentials(
    upstream,
):
    origin = f'http://127.0.0.1:{upstream.port}'
    with proxying(origin) as port:
        response = send(
            port,
            (
                f'GET {origin}/styles/light.json?access_token=pk.x HTTP/1.1\r\n'
                'Host: attacker.invalid\r\n'
                'Cookie: accessKey=eyJ.token.here\r\n'
                'Authorization: Bearer eyJ.token.here\r\n'
                'Proxy-Connection: keep-alive\r\n'
                'Accept: application/json\r\n\r\n'
            ).encode(),
        )

    assert status_of(response) == 200
    assert response.endswith(b'style')
    [request] = upstream.received
    lines = request.decode().split('\r\n')
    assert lines[0] == 'GET /styles/light.json?access_token=pk.x HTTP/1.1'
    assert f'Host: 127.0.0.1:{upstream.port}' in lines
    assert 'Accept: application/json' in lines
    assert 'eyJ' not in request.decode()
    assert not [line for line in lines if line.lower().startswith('proxy-')]


class KeptAliveUpstream:
    """A map server that ignores `Connection: close`: it answers the first request
    and keeps reading, recording every byte that reaches it."""

    def __init__(self) -> None:
        self.received = b''
        self.server = socket.create_server(('127.0.0.1', 0))
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        connection, _ = self.server.accept()
        connection.settimeout(3)
        answered = False
        with connection:
            while True:
                try:
                    data = connection.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                self.received += data
                if not answered and b'\r\n\r\n' in self.received:
                    answered = True
                    connection.sendall(
                        b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\n'
                        b'Connection: keep-alive\r\n\r\nstyle'
                    )

    def close(self) -> None:
        self.server.close()


def test_a_second_request_on_a_kept_alive_connection_never_reaches_the_map_origin():
    # Found by security review: after the first relayed request the proxy copied
    # the client's later bytes upstream raw, Cookie included.
    upstream = KeptAliveUpstream()
    try:
        with proxying(f'http://127.0.0.1:{upstream.port}') as port:
            with socket.create_connection(('127.0.0.1', port), timeout=5) as client:
                client.sendall(
                    f'GET http://127.0.0.1:{upstream.port}/styles HTTP/1.1\r\n'
                    f'Host: 127.0.0.1:{upstream.port}\r\n\r\n'.encode()
                )
                first = client.recv(65536)
                client.sendall(
                    f'GET http://127.0.0.1:{upstream.port}/tiles HTTP/1.1\r\n'
                    f'Host: 127.0.0.1:{upstream.port}\r\n'
                    'Cookie: accessKey=eyJ.secret\r\n\r\n'.encode()
                )
                rest = b''
                try:
                    while chunk := client.recv(65536):
                        rest += chunk
                except OSError:
                    pass
    finally:
        upstream.close()

    assert status_of(first) == 200
    assert first.endswith(b'Connection: close\r\n\r\nstyle')
    assert b'keep-alive' not in first
    assert b'/styles' in upstream.received
    assert b'/tiles' not in upstream.received
    assert b'accessKey' not in upstream.received
    assert b'Cookie' not in upstream.received


@pytest.mark.parametrize(
    'request_line',
    [
        'GET http://127.0.0.1:{other}/ HTTP/1.1',
        'GET http://attacker.invalid/ HTTP/1.1',
        'GET https://127.0.0.1:{port}/ HTTP/1.1',
        'GET http://user@127.0.0.1:{port}/ HTTP/1.1',
    ],
)
def test_a_plain_http_fetch_from_anywhere_else_is_refused(upstream, request_line):
    with proxying(f'http://127.0.0.1:{upstream.port}') as port:
        response = send(
            port,
            (
                request_line.format(port=upstream.port, other=upstream.port + 1)
                + '\r\n\r\n'
            ).encode(),
        )

    assert status_of(response) == 403
    assert upstream.connections == 0


@pytest.mark.parametrize(
    'request_head, status',
    [
        ('POST {origin}/events HTTP/1.1\r\nContent-Length: 2\r\n\r\n{{}}', 405),
        ('GET /styles HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n', 400),
        ('GET {origin}/ HTTP/1.1\r\nContent-Length: 2\r\n\r\n{{}}', 400),
    ],
    ids=['not-a-fetch', 'not-a-proxy-request', 'fetch-with-a-body'],
)
def test_anything_but_a_plain_fetch_is_refused(upstream, request_head, status):
    origin = f'http://127.0.0.1:{upstream.port}'
    with proxying(origin) as port:
        response = send(port, request_head.format(origin=origin).encode())

    assert status_of(response) == status
    assert upstream.connections == 0


def test_each_decision_is_logged_without_the_path_or_query(upstream, caplog):
    caplog.set_level(logging.INFO, logger='harmony.worker.renderer.egress')
    origin = f'http://127.0.0.1:{upstream.port}'
    with proxying(origin) as port:
        send(port, f'GET {origin}/s?access_token=pk.x HTTP/1.1\r\n\r\n'.encode())
        send(port, b'GET http://attacker.invalid/x?q=1 HTTP/1.1\r\n\r\n')

    lines = [json.loads(r.getMessage()) for r in caplog.records]
    assert lines == [
        {
            'event': 'egress',
            'host': '127.0.0.1',
            'port': upstream.port,
            'allowed': True,
        },
        {'event': 'egress', 'host': 'attacker.invalid', 'port': 80, 'allowed': False},
    ]
    assert 'access_token' not in caplog.text
