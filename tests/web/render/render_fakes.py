"""Fakes for the render-route tests: users, dashboards, the cache and the renderer
service."""

from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import urlsplit

import redis
import requests
from flask import Flask
from flask_jwt_extended import decode_token
from flask_principal import ItemNeed
from jwt import PyJWTError

from models.python.permissions import DimensionFilter, QueryNeed
from web.server.security.permissions import SUPERUSER_NEED

# The deployment's configured origin (DEPLOYMENT_BASE_URL) in these tests.
DEPLOYMENT_ORIGIN = 'https://harmony.tests.invalid'

DASHBOARD_SLUG = 'malaria-overview'
# Emailed renders run inside the sender's signed-in request.
SENDER = {'X-Test-User': 'admin@tests.invalid'}
DASHBOARD_RESOURCE_ID = 7
STATE = 'StateName'  # an AUTHORIZABLE_DIMENSIONS entry in harmony_demo


def _policy(*include_values: str) -> QueryNeed:
    if include_values:
        return QueryNeed([DimensionFilter(STATE, include_values=include_values)])
    return QueryNeed([DimensionFilter(STATE, all_values=True)])


VIEW_DASHBOARD = ItemNeed('view_resource', DASHBOARD_RESOURCE_ID, 'dashboard')


@dataclass
class FakeUser:
    id: int
    username: str
    provides: FrozenSet = field(default_factory=frozenset)
    first_name: str = 'Test'
    last_name: str = 'User'
    is_authenticated: bool = True
    is_active: bool = True
    is_anonymous: bool = False
    from_jwt: bool = False

    def get_id(self) -> str:
        return str(self.id)

    def get_permissions(self) -> set:
        return set(self.provides)


USERS: Dict[str, FakeUser] = {
    user.username: user
    for user in (
        FakeUser(1, 'admin@tests.invalid', frozenset({SUPERUSER_NEED})),
        FakeUser(2, 'viewer@tests.invalid', frozenset({VIEW_DASHBOARD, _policy()})),
        FakeUser(
            3, 'north@tests.invalid', frozenset({VIEW_DASHBOARD, _policy('North')})
        ),
        FakeUser(
            4, 'north2@tests.invalid', frozenset({VIEW_DASHBOARD, _policy('North')})
        ),
        FakeUser(
            5, 'south@tests.invalid', frozenset({VIEW_DASHBOARD, _policy('South')})
        ),
        FakeUser(6, 'outsider@tests.invalid', frozenset({_policy()})),
    )
}


@dataclass
class FakeDashboard:
    slug: str
    resource_id: int


# The configuration store's public-access flag. When it is on, the sitewide
# unregistered role lets anonymous visitors view the dashboard.
PUBLIC_ACCESS = {'enabled': False}

DASHBOARDS = {DASHBOARD_SLUG: FakeDashboard(DASHBOARD_SLUG, DASHBOARD_RESOURCE_ID)}


class _FakeQuery:
    def __init__(self, rows: List[FakeDashboard]):
        self._rows = rows

    def first(self) -> Optional[FakeDashboard]:
        return self._rows[0] if self._rows else None

    def one(self) -> FakeDashboard:
        assert len(self._rows) == 1
        return self._rows[0]


def _lookup(search_fields: dict, case_sensitive: bool = True) -> List[FakeDashboard]:
    slug = search_fields['slug']
    return [
        dashboard
        for key, dashboard in DASHBOARDS.items()
        if key == slug or (not case_sensitive and key.lower() == slug.lower())
    ]


class FakeTransaction:
    """Stands in for `web.server.data.data_access.Transaction` on the dashboard table."""

    def __enter__(self) -> 'FakeTransaction':
        return self

    def __exit__(self, *exc) -> None:
        return None

    def find_all_by_fields(self, _model, search_fields, case_sensitive=True):
        return _FakeQuery(_lookup(search_fields, case_sensitive))

    def find_one_by_fields(self, _model, case_sensitive, search_fields):
        return _FakeQuery(_lookup(search_fields, case_sensitive)).first()


def fake_get_dashboard(slug, session=None):
    return FakeTransaction().find_one_by_fields(None, False, {'slug': slug})


class DictCache:
    def __init__(self) -> None:
        self.values: dict = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, timeout=None):
        self.values[key] = value

    def add(self, key, value, timeout=None):
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key):
        self.values.pop(key, None)


CONTENT_TYPES = {'pdf': 'application/pdf', 'png': 'image/png', 'jpeg': 'image/jpeg'}


@dataclass
class RenderCall:
    url: str
    params: dict
    identity: Optional[str]
    claims: dict
    timeout: object
    token_was_live: bool
    token_lifetime: Optional[int]


class FakeRenderResponse:
    def __init__(
        self, body: bytes, content_type: str = 'image/png', status_code: int = 200
    ) -> None:
        self.content = body
        self.status_code = status_code
        self.headers = {'Content-Type': content_type, 'Server-Timing': 'render;dur=42'}

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def close(self) -> None:
        return None


class FakeRenderer:
    """Replaces the `requests` module the web app calls the renderer service with.

    The body names the identity the minted `accessKey` token logs in as, so a
    test can tell whose data a render (and any cached copy of it) shows. Set
    `status_code` to make the renderer answer with an error.

    With `load_page`, it loads the dashboard page with the token as the browser
    would, through the app's real identity loading, and fails the render as
    `page_failed` unless the page answers 200. `before_page_load` runs first,
    for a change made while the render is queued.
    """

    RequestException = requests.RequestException

    def __init__(self, app: Flask) -> None:
        self._app = app
        self.calls: List[RenderCall] = []
        self.status_code = 200
        self.load_page = False
        self.before_page_load: Optional[Callable[[], None]] = None
        self.page_statuses: List[int] = []

    def post(self, url, json=None, timeout=None, stream=False):
        params = dict(json or {})
        token = params.get('token', '')
        identity, claims, lifetime = None, {}, None
        if token:
            try:
                with self._app.app_context():
                    decoded = decode_token(token)
            except PyJWTError:
                decoded = {'identity': f'undecodable:{token}'}
            identity = decoded.get('identity')
            claims = decoded.get('user_claims', {})
            if 'exp' in decoded:
                lifetime = decoded['exp'] - decoded['iat']
        render_id = claims.get('render')
        live = bool(render_id) and bool(
            self._app.cache.get(f'render-token:{render_id}')
        )
        self.calls.append(
            RenderCall(url, params, identity, claims, timeout, live, lifetime)
        )
        if self.load_page:
            if self.before_page_load is not None:
                self.before_page_load()
            page = urlsplit(params['url'])
            browser = self._app.test_client()
            # The test client replaces a Cookie header with its own jar.
            browser.set_cookie('localhost', 'accessKey', token)
            response = browser.get(f'{page.path}?{page.query}')
            self.page_statuses.append(response.status_code)
            if response.status_code != 200:
                return FakeRenderResponse(
                    b'{"error": "page_failed"}', 'application/json', status_code=502
                )
        return FakeRenderResponse(
            f'render-as:{identity}'.encode(),
            CONTENT_TYPES.get(params.get('format'), 'application/octet-stream'),
            status_code=self.status_code,
        )


class FakeRedis:
    """The redis-py calls cachelib's RedisCache makes, kept in a dict with each
    key's expiry. `expire` fails, as Redis can between two commands."""

    def __init__(self) -> None:
        self.values: Dict[str, bytes] = {}
        self.ttls: Dict[str, Optional[int]] = {}
        self.commands: List[Tuple[str, str]] = []

    def get(self, name: str) -> Optional[bytes]:
        return self.values.get(name)

    def set(self, name, value, ex=None, nx=False, **_kwargs):
        self.commands.append(('set', name))
        if nx and name in self.values:
            return None
        self.values[name] = value
        self.ttls[name] = ex
        return True

    def setex(self, name, time, value):
        self.commands.append(('setex', name))
        self.values[name] = value
        self.ttls[name] = time
        return True

    def setnx(self, name, value):
        self.commands.append(('setnx', name))
        if name in self.values:
            return False
        self.values[name] = value
        self.ttls[name] = None
        return True

    def expire(self, name, time):
        self.commands.append(('expire', name))
        raise redis.ConnectionError('connection lost between SETNX and EXPIRE')

    def delete(self, *names):
        for name in names:
            self.values.pop(name, None)
            self.ttls.pop(name, None)
        return len(names)
