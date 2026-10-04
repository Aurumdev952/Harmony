"""WP-1h: the renderer's real browser against a local dashboard origin.

Needs Playwright and Chromium, so it runs inside the renderer image (see the WP-1h
evidence for the command); elsewhere it is skipped. Nothing leaves the container:
the origins are local servers and every other destination is `.invalid`.
"""
import struct
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip('playwright')

# pylint: disable=wrong-import-position
from harmony.worker.renderer import browser
from harmony.worker.renderer.browser import render
from harmony.worker.renderer.errors import OutputTooLarge, PageFailed, RenderTimeout
from harmony.worker.renderer.server import RendererSettings
from harmony.worker.renderer.spec import RenderSpec, Viewport

TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJpZGVudGl0eSI6InRlc3QifQ.c2lnbmF0dXJl'
OTHER_TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJpZGVudGl0eSI6Im90aGVyIn0.c2lnbmF0dXJl'
READY = '<div id="dashboard-load-success"></div>'
SIGNAL_READY = f"document.body.insertAdjacentHTML('beforeend', '{READY}');"
SIGNAL_READY_AFTER_LOAD = f"window.addEventListener('load', () => setTimeout(() => {{ {SIGNAL_READY} }}, 300));"


def _page(body: str, script: str = '') -> bytes:
    return (
        '<!doctype html><html><head><style>html,body{margin:0}</style></head>'
        f'<body>{body}<script>{script}</script></body></html>'
    ).encode()


PAGES = {
    '/dashboard/ready': _page(
        '<h1>Malaria</h1>', f'setTimeout(() => {{ {SIGNAL_READY} }}, 200);'
    ),
    '/dashboard/never-ready': _page('<h1>Still loading</h1>'),
    '/dashboard/tall': _page(f'<div style="height:6000px">tall</div>{READY}'),
    '/dashboard/egress': _page(
        '<img src="http://tiles.invalid/0/0/0.png">'
        '<img src="{other}/pixel.png">'
        '<link rel="stylesheet" href="https://fonts.invalid/css">'
        '<img src="http://169.254.169.254/latest/meta-data/">'
        '<img src="http://[::1]:{other_port}/v6.png">'
        '<link rel="preconnect" href="{other}">'
        '<link rel="dns-prefetch" href="//prefetch.invalid">',
        "fetch('http://collect.invalid/beacon').catch(() => {});"
        "try { new WebSocket('ws://127.0.0.1:{other_port}/socket'); } catch (e) {}"
        f"{SIGNAL_READY_AFTER_LOAD}",
    ),
    '/dashboard/navigate-away': _page(
        '',
        "window.location.href = '{other}/dashboard/navigate-away';"
        f"setTimeout(() => {{ {SIGNAL_READY} }}, 1000);",
    ),
    '/dashboard/storage': _page(
        '',
        "fetch('/seen?value=' + (localStorage.getItem('seen') || 'none'))"
        f".then(() => {{ localStorage.setItem('seen', 'yes'); {SIGNAL_READY} }});",
    ),
}


def _chromium_flags() -> set[str]:
    """The command-line flags of every running Chromium process."""
    flags: set[str] = set()
    for cmdline in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            args = cmdline.read_bytes().split(b'\0')
        except OSError:
            continue
        if args and b'chrom' in args[0]:
            flags.update(arg.decode() for arg in args if arg.startswith(b'--'))
    return flags


class Origin:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.other_port = 0
        self.chromium_flags: list[set[str]] = []
        self.connections = 0

    def handler(self):
        origin = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                cookie = self.headers.get('Cookie', '')
                origin.requests.append({'path': self.path, 'cookie': cookie})
                path = self.path.split('?')[0]
                if path == '/login':
                    self._send(200, _page('<form>log in</form>'))
                elif path == '/dashboard/broken':
                    self._send(500, b'error')
                elif path == '/dashboard/redirect-away':
                    # Same path on another origin: only the origin differs.
                    self.send_response(302)
                    self.send_header(
                        'Location', f'http://127.0.0.1:{origin.other_port}{path}'
                    )
                    self.end_headers()
                elif path in PAGES:
                    if f'accessKey={TOKEN}' not in cookie and (
                        f'accessKey={OTHER_TOKEN}' not in cookie
                    ):
                        self.send_response(302)
                        self.send_header('Location', f'/login?next={path}')
                        self.end_headers()
                        return
                    origin.chromium_flags.append(_chromium_flags())
                    body = (
                        PAGES[path]
                        .replace(
                            b'{other}',
                            f'http://127.0.0.1:{origin.other_port}'.encode(),
                        )
                        .replace(b'{other_port}', str(origin.other_port).encode())
                    )
                    self._send(200, body)
                else:
                    self._send(204, b'')

            def _send(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header('Content-Type', 'text/html')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                return

        return Handler


@contextmanager
def _serving(origin: Origin) -> Iterator[int]:
    class CountingServer(ThreadingHTTPServer):
        def verify_request(self, request, client_address) -> bool:
            # Counts connections that never send a request, such as preconnects.
            origin.connections += 1
            return True

    server = CountingServer(('127.0.0.1', 0), origin.handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(name='origins')
def fixture_origins():
    """The dashboard origin, plus a second local origin the page must not reach."""
    dashboard, other = Origin(), Origin()
    with _serving(dashboard) as port, _serving(other) as other_port:
        dashboard.other_port = other_port
        yield f'http://127.0.0.1:{port}', dashboard, other


def _settings(origin: str, **overrides) -> RendererSettings:
    values = dict(
        allowed_origin=origin,
        port=0,
        max_timeout_seconds=30.0,
        max_bytes=25 * 1024 * 1024,
        concurrency=1,
        max_page_height=2000,
    )
    values.update(overrides)
    return RendererSettings(**values)


def _spec(origin: str, path: str, **overrides) -> RenderSpec:
    values = dict(
        url=f'{origin}{path}?screenshot=1',
        token=TOKEN,
        format='png',
        viewport=Viewport(1280, 800),
        full_page=False,
        pdf_page_size='A4',
        pdf_landscape=False,
        timeout_seconds=20.0,
    )
    values.update(overrides)
    return RenderSpec(**values)


def _png_size(content: bytes):
    assert content[:8] == b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II', content[16:24])


def test_png_is_rendered_signed_in_after_the_ready_signal(origins):
    origin, dashboard, _ = origins

    output = render(_spec(origin, '/dashboard/ready'), _settings(origin))

    assert _png_size(output.content) == (1280, 800)
    [page_load] = [r for r in dashboard.requests if r['path'].startswith('/dashboard')]
    assert page_load['cookie'] == f'accessKey={TOKEN}'


def test_pdf_and_jpeg_are_rendered(origins):
    origin, _, _ = origins

    pdf = render(_spec(origin, '/dashboard/ready', format='pdf'), _settings(origin))
    jpeg = render(_spec(origin, '/dashboard/ready', format='jpeg'), _settings(origin))

    assert pdf.content.startswith(b'%PDF-')
    assert jpeg.content.startswith(b'\xff\xd8\xff')


def test_full_page_capture_is_clipped_at_the_height_limit(origins):
    origin, _, _ = origins

    output = render(
        _spec(origin, '/dashboard/tall', full_page=True),
        _settings(origin, max_page_height=2000),
    )

    assert _png_size(output.content) == (1280, 2000)


def test_every_other_destination_is_blocked_and_recorded(origins):
    origin, _, other = origins

    output = render(_spec(origin, '/dashboard/egress'), _settings(origin))

    assert {
        'tiles.invalid',
        'fonts.invalid',
        'collect.invalid',
        '127.0.0.1',
        '169.254.169.254',
        '::1',
    } <= set(output.blocked_hosts)
    # Neither the image, the preconnect hint nor the WebSocket reached it.
    assert other.requests == []
    assert other.connections == 0


def test_the_proxy_fence_holds_even_if_the_request_guard_lets_everything_through(
    origins, monkeypatch
):
    origin, _, other = origins
    monkeypatch.setattr(browser, 'is_allowed', lambda url, allowed_origin: True)

    render(_spec(origin, '/dashboard/egress'), _settings(origin))

    assert other.requests == []
    assert other.connections == 0


def test_a_redirect_to_another_origin_fails_and_never_reaches_it(origins):
    origin, _, other = origins

    with pytest.raises(PageFailed):
        render(_spec(origin, '/dashboard/redirect-away'), _settings(origin))

    assert other.requests == []
    assert other.connections == 0


def test_the_page_cannot_navigate_itself_to_another_origin(origins):
    origin, _, other = origins

    try:
        render(_spec(origin, '/dashboard/navigate-away'), _settings(origin))
    except PageFailed:
        pass

    assert other.requests == []
    assert other.connections == 0


@pytest.mark.parametrize(
    'url',
    [
        'http://169.254.169.254/latest/meta-data/',
        'http://[::1]:{port}/dashboard/ready',
        'http://127.0.0.1:{other_port}/dashboard/ready',
        'http://127.0.0.1:{port}@127.0.0.1:{other_port}/dashboard/ready',
    ],
)
def test_render_refuses_a_spec_off_the_allowed_origin_without_a_browser(origins, url):
    origin, dashboard, other = origins
    port = origin.rsplit(':', 1)[1]
    spec = _spec(origin, '/dashboard/ready')
    spec = RenderSpec(
        **{
            **spec.__dict__,
            'url': url.format(port=port, other_port=dashboard.other_port),
        }
    )

    with pytest.raises(PageFailed):
        render(spec, _settings(origin))

    assert dashboard.requests == []
    assert other.requests == []


def test_chromium_runs_with_its_sandbox(origins):
    origin, dashboard, _ = origins

    render(_spec(origin, '/dashboard/ready'), _settings(origin))

    [flags] = dashboard.chromium_flags
    assert flags, 'no Chromium process was found while the page loaded'
    assert '--no-sandbox' not in flags
    assert '--no-zygote' not in flags


def test_a_refused_token_redirect_to_login_fails_the_render(origins):
    origin, _, _ = origins

    with pytest.raises(PageFailed):
        render(_spec(origin, '/dashboard/ready', token='a.b.c'), _settings(origin))


def test_a_page_error_fails_the_render(origins):
    origin, _, _ = origins

    with pytest.raises(PageFailed):
        render(_spec(origin, '/dashboard/broken'), _settings(origin))


def test_a_page_that_never_signals_ready_times_out_on_the_deadline(origins):
    origin, _, _ = origins
    started = time.monotonic()

    with pytest.raises(RenderTimeout):
        render(
            _spec(origin, '/dashboard/never-ready', timeout_seconds=3.0),
            _settings(origin),
        )

    assert time.monotonic() - started < 10


def test_output_over_the_size_limit_is_refused(origins):
    origin, _, _ = origins

    with pytest.raises(OutputTooLarge):
        render(_spec(origin, '/dashboard/ready'), _settings(origin, max_bytes=100))


def test_nothing_from_one_render_survives_into_the_next(origins):
    origin, dashboard, _ = origins

    render(_spec(origin, '/dashboard/storage'), _settings(origin))
    render(_spec(origin, '/dashboard/storage', token=OTHER_TOKEN), _settings(origin))

    seen = [r for r in dashboard.requests if r['path'].startswith('/seen')]
    assert [r['path'] for r in seen] == ['/seen?value=none', '/seen?value=none']
    assert seen[1]['cookie'] == f'accessKey={OTHER_TOKEN}'
