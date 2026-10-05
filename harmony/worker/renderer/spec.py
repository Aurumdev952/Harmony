'''What the renderer accepts as a render request.

The body is a JSON object with exactly the fields below. Anything else is refused,
so a caller cannot plant cookies, scripts or another page into the browser.
'''

import json
import re
from dataclasses import dataclass
from typing import Any, NamedTuple

from harmony.worker.renderer.egress import origin_of
from harmony.worker.renderer.errors import InvalidRenderRequest

__all__ = ['InvalidRenderRequest', 'RenderSpec', 'Viewport', 'parse_render_request']

FORMATS = ('pdf', 'png', 'jpeg')
# Kept in step with web/server/routes/views/page_renderer.py.
WIDTHS = range(320, 3841)
HEIGHTS = range(240, 4321)
PDF_PAGE_SIZES = ('A3', 'A4', 'A5', 'Legal', 'Letter', 'Tabloid')
MAX_TOKEN_LENGTH = 8192
JWT = re.compile(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*')
FIELDS = {'url', 'token', 'format', 'viewport', 'full_page', 'pdf', 'timeout_seconds'}


class Viewport(NamedTuple):
    width: int
    height: int


DEFAULT_VIEWPORT = Viewport(1280, 1024)


@dataclass(frozen=True)
class RenderSpec:
    url: str
    token: str
    format: str
    viewport: Viewport
    full_page: bool
    pdf_page_size: str
    pdf_landscape: bool
    timeout_seconds: float


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _url(value: Any, allowed_origin: str) -> str:
    if not isinstance(value, str) or origin_of(value) is None:
        raise InvalidRenderRequest('url is not an http(s) URL without credentials')
    if origin_of(value) != origin_of(allowed_origin):
        raise InvalidRenderRequest('url is not on the allowed origin')
    return value


def _token(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_TOKEN_LENGTH
        or not JWT.fullmatch(value)
    ):
        raise InvalidRenderRequest('token is not a JWT')
    return value


def _viewport(value: Any) -> Viewport:
    if (
        not isinstance(value, dict)
        or set(value) != {'width', 'height'}
        or not _is_int(value['width'])
        or not _is_int(value['height'])
        or value['width'] not in WIDTHS
        or value['height'] not in HEIGHTS
    ):
        raise InvalidRenderRequest('viewport is out of range')
    return Viewport(value['width'], value['height'])


def _pdf(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {'page_size', 'landscape'}
        or value['page_size'] not in PDF_PAGE_SIZES
        or not isinstance(value['landscape'], bool)
    ):
        raise InvalidRenderRequest('pdf options are invalid')
    return value


def _timeout(value: Any, max_timeout_seconds: float) -> float:
    if not (_is_int(value) or isinstance(value, float)) or not value > 0:
        raise InvalidRenderRequest('timeout_seconds is not a positive number')
    return float(min(value, max_timeout_seconds))


def parse_render_request(
    body: bytes, *, allowed_origin: str, max_timeout_seconds: float
) -> RenderSpec:
    try:
        request = json.loads(body.decode('utf-8'))
    except ValueError as error:
        raise InvalidRenderRequest('body is not JSON') from error
    if not isinstance(request, dict):
        raise InvalidRenderRequest('body is not a JSON object')
    unknown = set(request) - FIELDS
    if unknown:
        raise InvalidRenderRequest(f'unknown fields: {sorted(unknown)}')
    missing = {'url', 'token', 'format'} - set(request)
    if missing:
        raise InvalidRenderRequest(f'missing fields: {sorted(missing)}')
    if request['format'] not in FORMATS:
        raise InvalidRenderRequest('format is not pdf, png or jpeg')
    full_page = request.get('full_page', False)
    if not isinstance(full_page, bool):
        raise InvalidRenderRequest('full_page is not a boolean')
    pdf = _pdf(request.get('pdf', {'page_size': 'A4', 'landscape': False}))
    return RenderSpec(
        url=_url(request['url'], allowed_origin),
        token=_token(request['token']),
        format=request['format'],
        viewport=_viewport(request.get('viewport', DEFAULT_VIEWPORT._asdict())),
        full_page=full_page,
        pdf_page_size=pdf['page_size'],
        pdf_landscape=pdf['landscape'],
        timeout_seconds=_timeout(
            request.get('timeout_seconds', max_timeout_seconds), max_timeout_seconds
        ),
    )
