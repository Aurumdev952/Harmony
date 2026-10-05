'''Renders one dashboard page in a fresh headless Chromium (Playwright).

Every render launches its own browser and closes it in `finally`, so no cookie,
cache or storage outlives one user's render.

The page runs with the user's token and loads content the renderer does not
control, so it is fenced three times (threat model in
docs/modernisation/work/WP-1h.md):
- a request route aborts every request off the allowed origin, except fetches
  (never navigations) from the configured map origins, and every WebSocket is
  refused. Playwright does not route redirect hops; the next two layers hold
  those;
- Chromium may only connect directly to the allowed scheme, host and port; every
  other connection, preconnects and WebRTC included, goes to the egress proxy,
  which relays only to the map origins, or, without one, to a proxy that does
  not exist;
- the Compose network has no route out except through the egress proxy.
Chromium keeps its sandbox.

A dashboard whose map needs a host it cannot reach would wait out the whole
deadline, so once a fetch or XHR the page made was refused or failed at a map
origin, it has `blocked_grace_seconds` left to signal ready. The ready signal
waits only on those: a blocked frame, image, font, stylesheet or WebSocket
renders as an empty box and does not start the clock, so an iframe tile to a
host off the list exports as a blank frame.
'''

import asyncio
import re
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import (
    ProxySettings,
    Request,
    Route,
    WebSocketRoute,
    async_playwright,
)

from harmony.worker.renderer.egress import is_allowed, origin_of
from harmony.worker.renderer.errors import (
    EgressBlocked,
    OutputTooLarge,
    PageFailed,
    RenderTimeout,
)
from harmony.worker.renderer.server import RendererSettings, RenderOutput
from harmony.worker.renderer.spec import RenderSpec

# The screenshot app adds this element once every tile has loaded.
READY_SELECTOR = '#dashboard-load-success'

# Without an egress proxy, every connection Chromium does not make directly to
# the allowed origin goes here. `.invalid` never resolves, so those connections
# fail.
BLACKHOLE_PROXY = 'http://egress-blocked.invalid:3128'
CHROMIUM_ARGS = [
    # WebRTC would otherwise send UDP around the proxy.
    '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
    '--dns-prefetch-disable',
]
NET_ERROR = re.compile(r'net::ERR_[A-Z_]+')
# The page cancelled the request itself (a replaced image, a superseded fetch).
CANCELLED = 'net::ERR_ABORTED'
# The requests the ready signal waits on: tile data and map styles and tiles.
AWAITED_RESOURCE_TYPES = frozenset({'fetch', 'xhr'})

# Carried over from the urlbox PDF options: charts whose SVG overflows its box
# would otherwise be clipped in print.
PDF_CSS = 'svg:not(:root) { overflow: visible !important; }'
PDF_INIT_SCRIPT = '''
window.addEventListener('resize', () => {
  document.querySelectorAll('.visualization > div > svg').forEach((svg) => {
    svg.setAttribute('height', '1px');
  });
});
'''


async def _capture(page, spec: RenderSpec, settings: RendererSettings) -> bytes:
    if spec.format == 'pdf':
        await page.emulate_media(media='screen')
        await page.add_style_tag(content=PDF_CSS)
        return await page.pdf(
            format=spec.pdf_page_size,
            landscape=spec.pdf_landscape,
            print_background=True,
        )
    options = {'type': spec.format, 'full_page': spec.full_page}
    if spec.format == 'jpeg':
        options['quality'] = 100
    if spec.full_page:
        height = await page.evaluate('document.documentElement.scrollHeight')
        if height > settings.max_page_height:
            options['clip'] = {
                'x': 0,
                'y': 0,
                'width': spec.viewport.width,
                'height': settings.max_page_height,
            }
    return await page.screenshot(**options)


def _host(url: str) -> str:
    parts = urlsplit(url)
    return parts.hostname or parts.scheme or 'unknown'


def _is_requested_page(current: str, requested: str, origin: str) -> bool:
    return (
        origin_of(current) == origin_of(origin)
        and urlsplit(current).path == urlsplit(requested).path
    )


def _proxy(settings: RendererSettings) -> ProxySettings:
    scheme, host, port = origin_of(settings.allowed_origin)  # type: ignore[misc]
    bracketed = f'[{host}]' if ':' in host else host
    # Chromium applies the last matching rule. `<-loopback>` first sends loopback
    # addresses through the proxy too; the origin rule after it still wins for
    # the origin itself, even when that is a loopback address.
    return {
        'server': settings.egress_proxy or BLACKHOLE_PROXY,
        'bypass': f'<-loopback>,{scheme}://{bracketed}:{port}',
    }


def _is_map_url(url: str, settings: RendererSettings) -> bool:
    origin = origin_of(url)
    return origin is not None and origin in {origin_of(m) for m in settings.map_origins}


async def _wait_until_ready(page, egress_failed: asyncio.Event, needed, grace) -> None:
    '''Waits for the ready signal. Once the page needed something it could not
    get, it has `grace` seconds left, then the render fails.
    '''
    ready = asyncio.ensure_future(
        page.wait_for_selector(READY_SELECTOR, state='attached')
    )
    failed = asyncio.ensure_future(egress_failed.wait())
    try:
        await asyncio.wait({ready, failed}, return_when=asyncio.FIRST_COMPLETED)
        if not ready.done():
            # The page may still finish without what it was refused.
            await asyncio.wait({ready}, timeout=grace)
        if not ready.done():
            raise EgressBlocked(f'the page needed {", ".join(sorted(needed))}')
        ready.result()
    finally:
        for task in (ready, failed):
            task.cancel()


async def _render(spec: RenderSpec, settings: RendererSettings, blocked: set[str]):
    origin = settings.allowed_origin
    needed: set[str] = set()
    egress_failed = asyncio.Event()

    def refused(request: Request) -> None:
        host = _host(request.url)
        awaited = request.resource_type in AWAITED_RESOURCE_TYPES
        if awaited and host not in settings.ignored_blocked_hosts:
            needed.add(host)
            egress_failed.set()

    async def guard(route: Route) -> None:
        request = route.request
        if is_allowed(
            request.url,
            origin,
            settings.map_origins,
            is_navigation=request.is_navigation_request(),
        ):
            await route.continue_()
        else:
            blocked.add(_host(request.url))
            refused(request)
            await route.abort('blockedbyclient')

    async def refuse_web_socket(web_socket: WebSocketRoute) -> None:
        # Never connected to a server: the page's socket just closes.
        blocked.add(_host(web_socket.url))
        await web_socket.close()

    def map_request_failed(request) -> None:
        # The egress proxy refused or could not reach a map origin.
        if _is_map_url(request.url, settings) and request.failure != CANCELLED:
            refused(request)

    def map_response(response) -> None:
        # A map style or tile that answers with an error never loads; a 404 is a
        # tile outside the map's coverage, which the map draws without.
        if _is_map_url(response.url, settings) and response.status >= 400:
            if response.status != 404:
                refused(response.request)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            chromium_sandbox=True, args=CHROMIUM_ARGS, proxy=_proxy(settings)
        )
        try:
            context = await browser.new_context(
                viewport={'width': spec.viewport.width, 'height': spec.viewport.height},
                service_workers='block',
                accept_downloads=False,
            )
            # The render deadline bounds everything; Playwright's own 30 s
            # per-action default would cut slow dashboards short of it.
            context.set_default_timeout(spec.timeout_seconds * 1000)
            await context.route('**/*', guard)
            await context.route_web_socket(re.compile('.*'), refuse_web_socket)
            # A cookie is scoped to a host, not a port: the guard and the proxy
            # are what keep the token off the host's other ports.
            await context.add_cookies(
                [
                    {
                        'name': 'accessKey',
                        'value': spec.token,
                        'url': origin,
                        'httpOnly': True,
                        'sameSite': 'Strict',
                    }
                ]
            )
            if spec.format == 'pdf':
                await context.add_init_script(PDF_INIT_SCRIPT)
            page = await context.new_page()
            page.on('requestfailed', map_request_failed)
            page.on('response', map_response)
            try:
                response = await page.goto(spec.url, wait_until='domcontentloaded')
            except PlaywrightError as error:
                found = NET_ERROR.search(error.message)
                code = found.group() if found else 'error'
                raise PageFailed(f'dashboard page did not load ({code})') from None
            if response is None or not response.ok:
                status = response.status if response else 'no response'
                raise PageFailed(f'dashboard page answered {status}')
            if not _is_requested_page(page.url, spec.url, origin):
                # Usually the token was refused and the app sent the browser to
                # log in. A redirect off the origin was aborted before this.
                raise PageFailed('dashboard page redirected elsewhere')
            await _wait_until_ready(
                page, egress_failed, needed, settings.blocked_grace_seconds
            )
            if not _is_requested_page(page.url, spec.url, origin):
                raise PageFailed('dashboard page navigated elsewhere')
            return await _capture(page, spec, settings)
        finally:
            await browser.close()


def render(spec: RenderSpec, settings: RendererSettings) -> RenderOutput:
    requested = origin_of(spec.url)
    if requested is None or requested != origin_of(settings.allowed_origin):
        # parse_render_request refuses this already. It is checked again before
        # any browser starts, because the token must never go anywhere else.
        raise PageFailed('url is not on the allowed origin')
    blocked: set[str] = set()
    try:
        content = asyncio.run(
            asyncio.wait_for(_render(spec, settings, blocked), spec.timeout_seconds)
        )
    except asyncio.TimeoutError as error:
        raise RenderTimeout(f'no render within {spec.timeout_seconds:.0f}s') from error
    if len(content) > settings.max_bytes:
        raise OutputTooLarge(f'{len(content)} bytes')
    return RenderOutput(content=content, blocked_hosts=tuple(sorted(blocked)))
