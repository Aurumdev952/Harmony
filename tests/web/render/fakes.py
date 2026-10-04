"""Fakes for the render-route tests: users, dashboards, the cache and urlbox."""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterator, List, Optional

from flask import Flask
from flask_jwt_extended import decode_token
from flask_principal import ItemNeed
from jwt import PyJWTError

from models.python.permissions import DimensionFilter, QueryNeed
from web.server.security.permissions import SUPERUSER_NEED

# The deployment's configured origin (DEPLOYMENT_BASE_URL) in these tests.
DEPLOYMENT_ORIGIN = 'https://harmony.tests.invalid'

DASHBOARD_SLUG = 'malaria-overview'
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


@dataclass
class RenderCall:
    url: str
    params: dict
    identity: Optional[str]
    claims: dict


class FakeRenderResponse:
    status_code = 200

    def __init__(self, body: bytes) -> None:
        self.content = body
        self.url = 'https://renderer.invalid/'

    def iter_content(self, chunk_size=2048) -> Iterator[bytes]:
        yield self.content


class FakeRenderer:
    """Replaces the `requests` module the renderer calls urlbox with.

    The body names the identity the minted `accessKey` token logs in as, so a
    test can tell whose data a render (and any cached copy of it) shows.
    """

    def __init__(self, app: Flask) -> None:
        self._app = app
        self.calls: List[RenderCall] = []

    def get(self, url, params=None, stream=False, timeout=None):
        params = dict(params or {})
        cookie = params.get('cookie', '')
        token = cookie[len('accessKey=') :] if cookie.startswith('accessKey=') else ''
        identity, claims = None, {}
        if token:
            try:
                with self._app.app_context():
                    decoded = decode_token(token)
            except PyJWTError:
                decoded = {'identity': f'undecodable:{token}'}
            identity = decoded.get('identity')
            claims = decoded.get('user_claims', {})
        self.calls.append(RenderCall(url, params, identity, claims))
        return FakeRenderResponse(f'render-as:{identity}'.encode())
