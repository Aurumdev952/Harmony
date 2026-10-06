'''Dashboard exports, rendered by the self-hosted renderer service (WP-1h).

The renderer's browser loads this app's own dashboard page over the internal
network, signed in with a render token for the user the export is made as.
'''

import json
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Optional
from urllib.parse import urlparse, urlsplit

import requests
from cachelib import FileSystemCache, RedisCache
from flask import current_app
from flask_user import current_user
from werkzeug.exceptions import HTTPException, ServiceUnavailable, Unauthorized

from config import settings
from log import LOG
from models.alchemy.dashboard import Dashboard
from models.alchemy.user import User
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
READ_CHUNK_BYTES = 64 * 1024
# A renderer error body is `{"error": "<code>"}`; only a code this shape is logged.
ERROR_BODY_MAX_BYTES = 1024
ERROR_CODE = re.compile(r'[a-z_]{1,64}')
# The renderer runs few renders at once (RENDERER_CONCURRENCY, 2), so one
# account's renders must not fill it and leave everyone else queueing until
# their deadlines. Kept below the renderer's concurrency
# (tests/worker/test_renderer_web_drift.py).
MAX_RENDERS_IN_FLIGHT_PER_ACCOUNT = 1
SLOT_POLL_SECONDS = 0.5
# An emailed render runs inside the sender's share request, after its
# notifications went out, so it waits this long for the sender's slot (for
# example behind their Overview thumbnails) before the email goes without it.
EMAIL_SLOT_WAIT_SECONDS = 30

CONTENT_TYPES = {'pdf': 'application/pdf', 'png': 'image/png', 'jpeg': 'image/jpeg'}

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 1024
# The ranges the renderer service accepts (harmony/worker/renderer/spec.py),
# copied because this app's image runs Python 3.8, which cannot import the
# renderer package, until WP-3b. tests/worker/test_renderer_web_drift.py fails
# when they drift.
WIDTHS = range(320, 3841)
HEIGHTS = range(240, 4321)
PDF_PAGE_SIZES = ('A3', 'A4', 'A5', 'Legal', 'Letter', 'Tabloid')


class RendersInFlight(ServiceUnavailable):
    description = 'Your other exports are still rendering. Try again shortly.'


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


def deployment_origin(deployment_base_url):
    """The configured DEPLOYMENT_BASE_URL as a bare https origin, or ValueError.

    Renders send a minted token to this origin and emails send links to it, so it
    must name exactly one host: no userinfo (`https://real@attacker`), path,
    query or fragment.
    """
    parts = urlsplit(deployment_base_url or "")
    try:
        has_valid_port = parts.port is None or parts.port > 0
    except ValueError:
        has_valid_port = False
    if (
        not has_valid_port
        or parts.scheme != "https"
        or not parts.hostname
        or "@" in parts.netloc
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "DEPLOYMENT_BASE_URL must be an https origin with no userinfo, path, "
            f"query or fragment: {deployment_base_url!r}"
        )
    return f"https://{parts.netloc}"


def deployment_dashboard_url(name, locale=None):
    '''The dashboard page's public URL, for links sent to people.

    Built from the configured DEPLOYMENT_BASE_URL, never from the request, so a
    forged Host cannot point an emailed link elsewhere. Renders use
    RENDER_WEB_ORIGIN instead.
    '''
    origin = deployment_origin(current_app.zen_config.general.DEPLOYMENT_BASE_URL)
    return origin + _dashboard_path(name, locale)


def _dashboard_path(name, locale=None):
    '''The dashboard page's path. `url_for` would prefix the request's script
    root, which gunicorn takes from a `SCRIPT_NAME` request header.
    '''
    return current_app.url_map.bind('').build(
        'dashboard.grid_dashboard', {'locale': locale, 'name': name}
    )


def _page_url(locale, name, output_format, session_hash, is_thumbnail):
    path = _dashboard_path(name, locale)
    query = 'screenshot=1'
    if output_format == 'pdf':
        query += '&pdf=1'
    if is_thumbnail:
        query += '&thumbnail=1'
    hash_suffix = f'#h={session_hash}' if session_hash else ''
    return f'{RENDER_WEB_ORIGIN}{path}?{query}{hash_suffix}'


def _int_arg(args: Mapping[str, str], name: str, allowed: range, default: int) -> int:
    value = args.get(name, '')
    # isdigit() alone accepts digits such as '²' that int() rejects.
    if not (value.isascii() and value.isdecimal()):
        return default
    return int(value) if int(value) in allowed else default


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


def _read_capped(response) -> Optional[bytes]:
    '''The body, or None once it passes RENDER_MAX_BYTES (never read further).'''
    declared = response.headers.get('Content-Length', '')
    if declared.isascii() and declared.isdecimal() and int(declared) > RENDER_MAX_BYTES:
        return None
    body = bytearray()
    for chunk in response.iter_content(READ_CHUNK_BYTES):
        body += chunk
        if len(body) > RENDER_MAX_BYTES:
            return None
    return bytes(body)


def _error_code(response, content_type: str) -> str:
    '''The renderer\'s error code, read from at most ERROR_BODY_MAX_BYTES of
    its JSON error body.'''
    if content_type != 'application/json':
        return 'no error code'
    body = b''
    for chunk in response.iter_content(ERROR_BODY_MAX_BYTES):
        body += chunk
        if len(body) > ERROR_BODY_MAX_BYTES:
            return 'no error code'
    try:
        code = json.loads(body).get('error')
    except (ValueError, AttributeError):
        return 'no error code'
    if isinstance(code, str) and ERROR_CODE.fullmatch(code):
        return code
    return 'no error code'


def _checked(response, output_format: str, name: str) -> Optional[RenderedDashboard]:
    expected = CONTENT_TYPES[output_format]
    content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
    content = None
    if response.status_code != 200:
        failure = _error_code(response, content_type)
    elif content_type != expected:
        failure = f'not {expected}'
    else:
        content = _read_capped(response)
        failure = 'over the size limit'
    if content is None:
        LOG.error(
            'Renderer failed to render %s of dashboard %s: status %s, %s, %s',
            output_format,
            name,
            response.status_code,
            content_type,
            failure,
        )
        return None
    LOG.info(
        'Rendered %s of dashboard %s: %s bytes, %s',
        output_format,
        name,
        len(content),
        response.headers.get('Server-Timing', ''),
    )
    return RenderedDashboard(content, expected)


def claim(cache, key: str, value: Any, timeout_seconds: int) -> bool:
    '''Sets `key` only if it is unset, expiring after `timeout_seconds`.

    On Redis this is one `SET NX EX`: cachelib's `add` is SETNX then EXPIRE, and
    a failure between the two would leave a claim that never expires. A
    FileSystemCache keeps an expired entry on disk, where `add` keeps failing
    although `get` misses it, so that entry is deleted and claimed again. On
    Redis a miss after a failed claim means the holder has just released it and
    another caller may hold a new one, so nothing is deleted there.
    '''
    backend = getattr(cache, 'cache', cache)
    if isinstance(backend, RedisCache):
        # pylint: disable=protected-access
        return bool(
            backend._write_client.set(
                f'{backend._get_prefix()}{key}',
                backend.serializer.dumps(value),
                nx=True,
                ex=timeout_seconds,
            )
        )
    if cache.add(key, value, timeout=timeout_seconds):
        return True
    if isinstance(backend, FileSystemCache) and cache.get(key) is None:
        cache.delete(key)
        return bool(cache.add(key, value, timeout=timeout_seconds))
    return False


def _claim_free_slot(account_id, ttl_seconds: int) -> Optional[str]:
    for slot in range(MAX_RENDERS_IN_FLIGHT_PER_ACCOUNT):
        key = f'render-in-flight:{account_id}:{slot}'
        if claim(current_app.cache, key, True, ttl_seconds):
            return key
    return None


@contextmanager
def _render_slot(ttl_seconds: int, wait_seconds: float = 0) -> Iterator[None]:
    '''Holds one of the signed-in account's render slots, waiting up to
    `wait_seconds` for one, or raises 503.

    Keyed on the session's account id, never on who the render is made as, so
    an emailed render counts against its sender. A slot expires with the render
    deadline, so a worker that dies mid-render cannot hold it.
    '''
    if not current_user.is_authenticated:
        raise Unauthorized()
    give_up_at = time.monotonic() + wait_seconds
    key = _claim_free_slot(current_user.id, ttl_seconds)
    while key is None:
        if time.monotonic() >= give_up_at:
            LOG.warning('Refused a render: the account has no free render slot')
            raise RendersInFlight()
        time.sleep(SLOT_POLL_SECONDS)
        key = _claim_free_slot(current_user.id, ttl_seconds)
    try:
        yield
    finally:
        current_app.cache.delete(key)


def render_dashboard(
    output_format: str,
    name: str,
    auth_user_email: str,
    *,
    locale=None,
    session_hash: str = '',
    is_thumbnail: bool = False,
    request_args: Optional[Mapping[str, str]] = None,
    slot_wait_seconds: float = 0,
) -> Optional[RenderedDashboard]:
    '''Render the dashboard `name` as `auth_user_email`, or None if it failed.

    Raises RendersInFlight (503) when the signed-in account already has
    MAX_RENDERS_IN_FLIGHT_PER_ACCOUNT renders running and none ends within
    `slot_wait_seconds`.

    When the caller renders as themselves, the token pins the digest of their
    query policy, so a policy change before the page loads gets the render nothing.
    '''
    with Transaction() as transaction:
        resource_id = (
            transaction.find_all_by_fields(Dashboard, {'slug': name}).one().resource_id
        )
        # The token names its account by id (WP-0k). An emailed render is made
        # as a recipient found by their stored, exact username.
        account = (
            current_user
            if _is_signed_in_as(auth_user_email)
            else transaction.find_one_by_fields(
                User, True, {'username': auth_user_email}
            )
        )
    if account is None:
        LOG.error('No account to render dashboard %s as', name)
        return None
    body = {
        'url': _page_url(locale, name, output_format, session_hash, is_thumbnail),
        'format': output_format,
        'timeout_seconds': RENDER_TIMEOUT_SECONDS,
        **_render_options(output_format, request_args or {}),
    }
    policy = query_policy_fingerprint() if _is_signed_in_as(auth_user_email) else None
    ttl_seconds = RENDER_TIMEOUT_SECONDS + RESPONSE_MARGIN_SECONDS
    with (
        _render_slot(ttl_seconds, slot_wait_seconds),
        render_token(
            account, resource_id, policy=policy, ttl_seconds=ttl_seconds
        ) as token,
    ):
        try:
            response = requests.post(
                f'{RENDERER_URL}/render',
                json={**body, 'token': token},
                timeout=(CONNECT_TIMEOUT_SECONDS, ttl_seconds),
                stream=True,
            )
            try:
                return _checked(response, output_format, name)
            finally:
                response.close()
        except requests.RequestException as error:
            LOG.error(
                'Renderer request for %s of dashboard %s failed: %s',
                output_format,
                name,
                type(error).__name__,
            )
            return None


def grid_dashboard_to_pdf(
    locale=None,
    name=None,
    *,
    auth_user_email,
    session_hash='',
    request_args=None,
    slot_wait_seconds=0,
):
    return render_dashboard(
        'pdf',
        name,
        auth_user_email,
        locale=locale,
        session_hash=session_hash,
        request_args=request_args,
        slot_wait_seconds=slot_wait_seconds,
    )


def grid_dashboard_to_thumbnail(
    locale=None, name=None, *, auth_user_email, slot_wait_seconds=0
):
    # A thumbnail is cached and shared, so no caller-supplied arg may shape it.
    return render_dashboard(
        'png',
        name,
        auth_user_email,
        locale=locale,
        is_thumbnail=True,
        slot_wait_seconds=slot_wait_seconds,
    )


def grid_dashboard_to_image(
    locale=None,
    name=None,
    *,
    auth_user_email,
    session_hash='',
    request_args=None,
    slot_wait_seconds=0,
):
    return render_dashboard(
        'jpeg',
        name,
        auth_user_email,
        locale=locale,
        session_hash=session_hash,
        request_args=request_args,
        slot_wait_seconds=slot_wait_seconds,
    )
