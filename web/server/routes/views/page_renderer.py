'''Dashboard exports, rendered by the self-hosted renderer service (WP-1h).

The renderer's browser loads this app's own dashboard page over the internal
network, signed in with a render token for the user the export is made as.
'''
from dataclasses import dataclass
from typing import Mapping, Optional
from urllib.parse import urlparse

import requests
from flask import current_app, url_for
from flask_user import current_user
from werkzeug.exceptions import HTTPException

from config import settings
from log import LOG
from models.alchemy.dashboard import Dashboard
from web.server.data.data_access import Transaction
from web.server.security.render_tokens import render_token
from web.server.security.signal_handlers import query_policy_fingerprint

RENDERER_URL = settings.getenv('RENDERER_URL', 'http://renderer:8080')
# The origin the renderer reaches this app on. Never taken from the request, so a
# forged Host header cannot send the token anywhere else.
RENDER_WEB_ORIGIN = settings.getenv('RENDER_WEB_ORIGIN', 'http://web:5000')

RENDER_TIMEOUT_SECONDS = 120
CONNECT_TIMEOUT_SECONDS = 5
# The renderer answers by its deadline; the margin covers sending the bytes back.
RESPONSE_MARGIN_SECONDS = 15
RENDER_MAX_BYTES = 25 * 1024 * 1024

CONTENT_TYPES = {'pdf': 'application/pdf', 'png': 'image/png', 'jpeg': 'image/jpeg'}

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 1024
# The ranges the renderer service accepts (harmony/worker/renderer/spec.py).
WIDTHS = range(320, 3841)
HEIGHTS = range(240, 4321)
PDF_PAGE_SIZES = ('A3', 'A4', 'A5', 'Legal', 'Letter', 'Tabloid')


@dataclass(frozen=True)
class RenderedDashboard:
    content: bytes
    content_type: str


def dashboard_page_args(dashboard_url):
    '''The locale and session hash in a link to a dashboard page.

    Nothing else is taken from a caller's link: a render always loads this app's
    own dashboard page, because it carries a token for the user it renders as.
    '''
    if not dashboard_url:
        return None, ''
    parsed = urlparse(dashboard_url)
    try:
        endpoint, args = current_app.url_map.bind('').match(parsed.path)
    except HTTPException:
        endpoint, args = None, {}
    locale = args.get('locale') if endpoint == 'dashboard.grid_dashboard' else None
    session_hash = parsed.fragment[2:] if parsed.fragment.startswith('h=') else ''
    return locale, session_hash


def _page_url(locale, name, output_format, session_hash, is_thumbnail):
    path = url_for('dashboard.grid_dashboard', locale=locale, name=name)
    query = 'screenshot=1'
    if output_format == 'pdf':
        query += '&pdf=1'
    if is_thumbnail:
        query += '&thumbnail=1'
    hash_suffix = f'#h={session_hash}' if session_hash else ''
    return f'{RENDER_WEB_ORIGIN}{path}?{query}{hash_suffix}'


def _int_arg(args: Mapping[str, str], name: str, allowed: range, default: int) -> int:
    value = args.get(name, '')
    return int(value) if value.isdigit() and int(value) in allowed else default


def _flag_arg(args: Mapping[str, str], name: str, default: bool) -> bool:
    return {'true': True, 'false': False}.get(args.get(name, '').lower(), default)


def _render_options(output_format: str, args: Mapping[str, str]) -> dict:
    '''The page shape, from the defaults and the few request args a caller may set.
    An arg outside what the renderer accepts falls back to its default.
    '''
    page_size = args.get('pdf_page_size')
    return {
        'viewport': {
            'width': _int_arg(args, 'width', WIDTHS, DEFAULT_WIDTH),
            'height': _int_arg(args, 'height', HEIGHTS, DEFAULT_HEIGHT),
        },
        'full_page': _flag_arg(args, 'full_page', output_format == 'jpeg'),
        'pdf': {
            'page_size': page_size if page_size in PDF_PAGE_SIZES else 'A4',
            'landscape': args.get('pdf_orientation') == 'landscape',
        },
    }


def _is_signed_in_as(username: str) -> bool:
    return bool(current_user.is_authenticated and current_user.username == username)


def _checked(response, output_format: str, name: str) -> Optional[RenderedDashboard]:
    expected = CONTENT_TYPES[output_format]
    content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
    size = len(response.content)
    if (
        response.status_code != 200
        or content_type != expected
        or size > RENDER_MAX_BYTES
    ):
        LOG.error(
            'Renderer failed to render %s of dashboard %s: status %s, %s, %s bytes',
            output_format,
            name,
            response.status_code,
            content_type,
            size,
        )
        return None
    LOG.info(
        'Rendered %s of dashboard %s: %s bytes, %s',
        output_format,
        name,
        size,
        response.headers.get('Server-Timing', ''),
    )
    return RenderedDashboard(response.content, expected)


def render_dashboard(
    output_format: str,
    name: str,
    auth_user_email: str,
    *,
    locale=None,
    session_hash: str = '',
    is_thumbnail: bool = False,
    request_args: Optional[Mapping[str, str]] = None,
) -> Optional[RenderedDashboard]:
    '''Render the dashboard `name` as `auth_user_email`, or None if it failed.

    When the caller renders as themselves, the token pins the digest of their
    query policy, so a policy change before the page loads gets the render nothing.
    '''
    with Transaction() as transaction:
        resource_id = (
            transaction.find_all_by_fields(Dashboard, {'slug': name}).one().resource_id
        )
    body = {
        'url': _page_url(locale, name, output_format, session_hash, is_thumbnail),
        'format': output_format,
        'timeout_seconds': RENDER_TIMEOUT_SECONDS,
        **_render_options(output_format, request_args or {}),
    }
    policy = query_policy_fingerprint() if _is_signed_in_as(auth_user_email) else None
    ttl_seconds = RENDER_TIMEOUT_SECONDS + RESPONSE_MARGIN_SECONDS
    with render_token(
        auth_user_email, resource_id, policy=policy, ttl_seconds=ttl_seconds
    ) as token:
        try:
            response = requests.post(
                f'{RENDERER_URL}/render',
                json={**body, 'token': token},
                timeout=(CONNECT_TIMEOUT_SECONDS, ttl_seconds),
            )
        except requests.RequestException as error:
            LOG.error(
                'Renderer request for %s of dashboard %s failed: %s',
                output_format,
                name,
                type(error).__name__,
            )
            return None
    return _checked(response, output_format, name)


def grid_dashboard_to_pdf(
    locale=None, name=None, *, auth_user_email, session_hash='', request_args=None
):
    return render_dashboard(
        'pdf',
        name,
        auth_user_email,
        locale=locale,
        session_hash=session_hash,
        request_args=request_args,
    )


def grid_dashboard_to_thumbnail(locale=None, name=None, *, auth_user_email):
    # A thumbnail is cached and shared, so no caller-supplied arg may shape it.
    return render_dashboard(
        'png', name, auth_user_email, locale=locale, is_thumbnail=True
    )


def grid_dashboard_to_image(
    locale=None, name=None, *, auth_user_email, session_hash='', request_args=None
):
    return render_dashboard(
        'jpeg',
        name,
        auth_user_email,
        locale=locale,
        session_hash=session_hash,
        request_args=request_args,
    )
