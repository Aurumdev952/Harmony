"""WP-1h: the renderer service's HTTP surface, with the browser faked."""

import http.client
import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Callable

import pytest

from harmony.worker.renderer.errors import (
    EgressBlocked,
    OutputTooLarge,
    PageFailed,
    RenderTimeout,
)
from harmony.worker.renderer.server import RendererSettings, RenderOutput, build_server
from harmony.worker.renderer.spec import RenderSpec

ORIGIN = 'http://web:5000'
TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJpZGVudGl0eSI6InRlc3QifQ.c2lnbmF0dXJl'
REQUEST = {
    'url': f'{ORIGIN}/dashboard/malaria?screenshot=1',
    'token': TOKEN,
    'format': 'png',
}


def settings(**overrides) -> RendererSettings:
    values = dict(
        allowed_origin=ORIGIN,
        port=0,
        max_timeout_seconds=120.0,
        max_bytes=1024,
        concurrency=2,
        max_page_height=16384,
    )
    values.update(overrides)
    return RendererSettings(**values)


@contextmanager
def serving(render: Callable, **overrides) -> Iterator[int]:
    server = build_server(settings(**overrides), render)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def call(port, method='POST', path='/render', body=None, raw=None, headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    payload = raw if raw is not None else (json.dumps(body).encode() if body else None)
    connection.request(method, path, body=payload, headers=headers or {})
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response, data


def png(spec: RenderSpec, _settings) -> RenderOutput:
    return RenderOutput(content=b'\x89PNG fake', blocked_hosts=('api.mapbox.com',))


def test_health_check_answers():
    with serving(png) as port:
        response, data = call(port, 'GET', '/healthz')

    assert response.status == 200
    assert data == b'ok'


@pytest.mark.parametrize(
    'output_format, content_type',
    [
        ('pdf', 'application/pdf'),
        ('png', 'image/png'),
        ('jpeg', 'image/jpeg'),
    ],
)
def test_render_answers_with_the_bytes_and_the_formats_content_type(
    output_format, content_type
):
    seen: list[RenderSpec] = []

    def render(spec, _settings):
        seen.append(spec)
        return RenderOutput(content=b'rendered', blocked_hosts=())

    with serving(render) as port:
        response, data = call(port, body={**REQUEST, 'format': output_format})

    assert response.status == 200
    assert response.getheader('Content-Type') == content_type
    assert data == b'rendered'
    assert seen[0].format == output_format
    assert seen[0].token == TOKEN


def test_render_time_is_reported():
    with serving(png) as port:
        response, _ = call(port, body=REQUEST)

    assert response.getheader('Server-Timing').startswith('render;dur=')


def test_render_is_logged_as_one_json_line_without_the_token(caplog):
    caplog.set_level(logging.INFO, logger='harmony.worker.renderer')
    with serving(png) as port:
        call(port, body=REQUEST)

    [line] = [
        r.getMessage() for r in caplog.records if '"event": "render"' in r.getMessage()
    ]
    entry = json.loads(line)
    assert entry['status'] == 200
    assert entry['format'] == 'png'
    assert entry['bytes'] == len(b'\x89PNG fake')
    assert entry['blocked_hosts'] == ['api.mapbox.com']
    assert isinstance(entry['duration_ms'], int)
    assert TOKEN not in caplog.text
    assert 'screenshot=1' not in caplog.text


@pytest.mark.parametrize(
    'error, status, code',
    [
        (RenderTimeout('deadline passed'), 504, 'render_timeout'),
        (PageFailed('dashboard page answered 500'), 502, 'page_failed'),
        (OutputTooLarge('30000000 bytes'), 502, 'output_too_large'),
        (EgressBlocked('the page needed styles.invalid'), 502, 'egress_blocked'),
    ],
)
def test_render_failures_map_to_statuses(error, status, code):
    def render(_spec, _settings):
        raise error

    with serving(render) as port:
        response, data = call(port, body=REQUEST)

    assert response.status == status
    assert json.loads(data)['error'] == code


def test_an_unexpected_failure_is_a_500_without_details():
    def render(_spec, _settings):
        raise RuntimeError(f'boom {TOKEN}')

    with serving(render) as port:
        response, data = call(port, body=REQUEST)

    assert response.status == 500
    assert TOKEN.encode() not in data


def test_output_over_the_limit_is_refused_even_if_the_browser_returned_it():
    def render(_spec, _settings):
        return RenderOutput(content=b'x' * 2048, blocked_hosts=())

    with serving(render, max_bytes=1024) as port:
        response, data = call(port, body=REQUEST)

    assert response.status == 502
    assert json.loads(data)['error'] == 'output_too_large'


def test_an_invalid_request_is_a_400_and_is_not_rendered():
    rendered = []
    with serving(lambda spec, s: rendered.append(spec)) as port:
        response, data = call(port, body={**REQUEST, 'url': 'http://attacker.invalid/'})

    assert response.status == 400
    assert json.loads(data)['error'] == 'invalid_request'
    assert rendered == []


def test_an_oversized_body_is_refused_before_it_is_read():
    with serving(png) as port:
        response, _ = call(port, raw=b'{' + b' ' * 20000 + b'}')

    assert response.status == 413


def test_a_body_without_a_length_is_refused():
    with serving(png) as port:
        response, _ = call(port, raw=b'', headers={'Transfer-Encoding': 'chunked'})

    assert response.status in (411, 413)


def test_a_length_in_non_ascii_digits_is_refused_and_logged(caplog):
    caplog.set_level(logging.INFO, logger='harmony.worker.renderer')
    with serving(png) as port:
        # '²' passes str.isdigit but not int().
        response, data = call(port, raw=b'{}', headers={'Content-Length': '\u00b2'})

    assert response.status == 411
    assert json.loads(data) == {'error': 'length_required'}
    [line] = [r.getMessage() for r in caplog.records if '"render"' in r.getMessage()]
    assert json.loads(line)['status'] == 411


@pytest.mark.parametrize(
    'method, path, status',
    [
        ('GET', '/render', 405),
        ('POST', '/healthz', 405),
        ('GET', '/', 404),
        ('POST', '/render/../admin', 404),
    ],
)
def test_only_the_two_endpoints_exist(method, path, status):
    with serving(png) as port:
        response, _ = call(
            port, method, path, body=REQUEST if method == 'POST' else None
        )

    assert response.status == status


def test_renders_beyond_the_concurrency_limit_wait_and_then_give_up():
    release = threading.Event()

    def slow(_spec, _settings):
        release.wait(10)
        return RenderOutput(content=b'done', blocked_hosts=())

    with serving(slow, concurrency=1) as port:
        first = threading.Thread(target=call, args=(port,), kwargs={'body': REQUEST})
        first.start()
        time.sleep(0.2)
        started = time.monotonic()
        response, data = call(port, body={**REQUEST, 'timeout_seconds': 1})
        waited = time.monotonic() - started
        release.set()
        first.join()

    assert response.status == 503
    assert json.loads(data)['error'] == 'busy'
    assert 0.9 <= waited < 5
