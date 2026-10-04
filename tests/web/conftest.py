"""A minimal Flask app that mounts the real render blueprint and the real
`/api2/storage/retrieve` resource behind the same Potion decorator as
`web/server/app.py`. Only the edges are faked: the dashboard table, the
configuration store, the cache, the login loader and the outbound urlbox call.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterator, List, Optional

import pytest

# Test-only placeholders read at import time by config modules.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-web-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('RENDERBOT_EMAIL', 'render-bot@tests.invalid')

# pylint: disable=wrong-import-position
from flask import Blueprint, Flask, g, request
from flask_jwt_extended import JWTManager, decode_token
from flask_login import LoginManager, current_user
from flask_potion import Api
from jwt import PyJWTError
from flask_principal import (
    AnonymousIdentity,
    Identity,
    ItemNeed,
    Principal,
    identity_loaded,
)

from models.python.permissions import DimensionFilter, QueryNeed
from web.server.api import thumbnail_storage_models
from web.server.api.thumbnail_storage_models import ThumbnailStorageResource
from web.server.routes import page_renderer as page_renderer_routes
from web.server.routes.page_renderer import PageRendererRouter
from web.server.routes.views import authentication
from web.server.routes.views import page_renderer as page_renderer_views
from web.server.routes.views.authentication import authentication_required
from web.server.security import permissions
from web.server.security.permissions import SUPERUSER_NEED

DASHBOARD_SLUG = 'malaria-overview'
DASHBOARD_RESOURCE_ID = 7
REGION = 'RegionName'


def _policy(*include_values: str) -> QueryNeed:
    if include_values:
        return QueryNeed([DimensionFilter(REGION, include_values=include_values)])
    return QueryNeed([DimensionFilter(REGION, all_values=True)])


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

    def get_id(self) -> str:
        return str(self.id)


USERS: Dict[str, FakeUser] = {
    user.username: user
    for user in (
        FakeUser(1, 'admin@tests.invalid', frozenset({SUPERUSER_NEED})),
        FakeUser(2, 'viewer@tests.invalid', frozenset({VIEW_DASHBOARD, _policy()})),
        FakeUser(3, 'north@tests.invalid', frozenset({VIEW_DASHBOARD, _policy('North')})),
        FakeUser(4, 'north2@tests.invalid', frozenset({VIEW_DASHBOARD, _policy('North')})),
        FakeUser(5, 'south@tests.invalid', frozenset({VIEW_DASHBOARD, _policy('South')})),
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
        token = cookie[len('accessKey='):] if cookie.startswith('accessKey=') else ''
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


@pytest.fixture(name='app', scope='session')
def fixture_app() -> Flask:
    """Session-scoped because Potion binds a resource class to a single `Api`."""
    here = os.path.dirname(__file__)
    app = Flask('tests.web', root_path=here, instance_path=here)
    app.config.update(
        TESTING=True,
        SERVER_NAME='harmony.tests.invalid',
        JWT_SECRET_KEY='tests-web-jwt-placeholder',
        JWT_TOKEN_LOCATION=['headers', 'cookies'],
        JWT_ACCESS_COOKIE_NAME='accessKey',
    )
    JWTManager(app)

    login_manager = LoginManager(app)

    @login_manager.request_loader
    def _load_user(_request):
        return USERS.get(request.headers.get('X-Test-User', ''))

    principals = Principal(app, use_sessions=False)

    @principals.identity_loader
    def _load_identity():
        if current_user.is_authenticated:
            return Identity(current_user.id)
        return AnonymousIdentity()

    @identity_loaded.connect_via(app)
    def _on_identity_loaded(_sender, identity):
        if current_user.is_authenticated:
            identity.provides |= set(current_user.provides)
        elif PUBLIC_ACCESS['enabled']:
            identity.provides.add(VIEW_DASHBOARD)

    @app.before_request
    def _request_logger():
        g.request_logger = logging.LoggerAdapter(logging.getLogger('tests.web'), {})

    # The renderer builds the page URL with url_for('dashboard.grid_dashboard').
    def grid_dashboard(locale=None, name=None):
        return ''

    dashboard_page = Blueprint('dashboard', __name__)
    dashboard_page.add_url_rule('/dashboard/<name>', 'grid_dashboard', grid_dashboard)
    dashboard_page.add_url_rule(
        '/<locale>/dashboard/<name>', 'grid_dashboard', grid_dashboard
    )
    app.register_blueprint(dashboard_page)
    app.register_blueprint(PageRendererRouter().generate_blueprint())

    api = Api(app, decorators=[authentication_required(is_api_request=True)], prefix='/api2')
    api.add_resource(ThumbnailStorageResource)
    return app


@pytest.fixture(name='public_access')
def fixture_public_access() -> Iterator[dict]:
    PUBLIC_ACCESS['enabled'] = False
    yield PUBLIC_ACCESS
    PUBLIC_ACCESS['enabled'] = False


@pytest.fixture(name='renderer')
def fixture_renderer(app: Flask, monkeypatch, public_access) -> FakeRenderer:
    def get_configuration(_key):
        return public_access['enabled']

    monkeypatch.setattr(authentication, 'get_configuration', get_configuration)
    monkeypatch.setattr(permissions, 'get_configuration', get_configuration)
    for module in (page_renderer_routes, page_renderer_views, thumbnail_storage_models):
        monkeypatch.setattr(module, 'Transaction', FakeTransaction, raising=False)
        monkeypatch.setattr(module, 'get_dashboard', fake_get_dashboard, raising=False)

    monkeypatch.setattr(app, 'cache', DictCache(), raising=False)
    renderer = FakeRenderer(app)
    monkeypatch.setattr(page_renderer_views, 'requests', renderer)
    return renderer


@pytest.fixture(name='client')
def fixture_client(app: Flask, renderer: FakeRenderer):
    return app.test_client()
