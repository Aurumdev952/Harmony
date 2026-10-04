'''Renders one dashboard page in a fresh headless Chromium (Playwright).

Every render launches its own browser and closes it in `finally`, so no cookie,
cache or storage outlives one user's render.
'''
import asyncio
from urllib.parse import urlsplit

from playwright.async_api import Route, async_playwright

from harmony.worker.renderer.egress import is_allowed
from harmony.worker.renderer.errors import OutputTooLarge, PageFailed, RenderTimeout
from harmony.worker.renderer.server import RendererSettings, RenderOutput
from harmony.worker.renderer.spec import RenderSpec

# The screenshot app adds this element once every tile has loaded.
READY_SELECTOR = '#dashboard-load-success'

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


async def _render(spec: RenderSpec, settings: RendererSettings, blocked: set[str]):
    origin = settings.allowed_origin

    async def guard(route: Route) -> None:
        url = route.request.url
        if is_allowed(url, origin):
            await route.continue_()
        else:
            blocked.add(urlsplit(url).hostname or urlsplit(url).scheme)
            await route.abort('blockedbyclient')

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            context = await browser.new_context(
                viewport={'width': spec.viewport.width, 'height': spec.viewport.height},
                service_workers='block',
                accept_downloads=False,
            )
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
            await context.route('**/*', guard)
            if spec.format == 'pdf':
                await context.add_init_script(PDF_INIT_SCRIPT)
            page = await context.new_page()
            response = await page.goto(spec.url, wait_until='domcontentloaded')
            if response is None or not response.ok:
                status = response.status if response else 'no response'
                raise PageFailed(f'dashboard page answered {status}')
            if urlsplit(page.url).path != urlsplit(spec.url).path:
                # The token was refused and the app sent the browser to log in.
                raise PageFailed('dashboard page redirected elsewhere')
            await page.wait_for_selector(READY_SELECTOR, state='attached')
            return await _capture(page, spec, settings)
        finally:
            await browser.close()


def render(spec: RenderSpec, settings: RendererSettings) -> RenderOutput:
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
