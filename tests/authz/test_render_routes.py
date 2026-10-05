'''The dashboard render routes (web/server/routes/page_renderer.py) and the
thumbnail store (/api2/storage/retrieve), run in-process.

The outbound render call (`requests.get` to urlbox) is replaced by a recorder:
these tests never contact urlbox. The database lookups of a dashboard by slug
are replaced by a fixed dashboard, Resource.id 7.
'''

from __future__ import annotations

import logging
import os
from types import SimpleNamespace

import pytest
from flask import Blueprint, Flask, g, request
from flask_jwt_extended import JWTManager, decode_token
from flask_login import LoginManager
from flask_potion import Api

from tests.authz.principals import (
    StandInUser,
    configuration,
    load_identity,
    principal_specs,
)
from web.server.api import thumbnail_storage_models
from web.server.routes import page_renderer as page_routes
from web.server.routes.views import page_renderer as page_views

_HERE = os.path.dirname(__file__)
SLUG = 'authz-dashboard'
RESOURCE_ID = 7
PRINCIPAL_HEADER = 'X-Authz-Principal'


class _Dashboards:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def find_all_by_fields(self, model, fields):
        assert fields == {'slug': SLUG}, fields
        dashboard = SimpleNamespace(resource_id=RESOURCE_ID)
        return SimpleNamespace(one=lambda: dashboard, first=lambda: dashboard)

    def find_one_by_fields(self, model, case_sensitive, search_fields):
        assert search_fields == {'slug': SLUG}, search_fields
        return SimpleNamespace(resource_id=RESOURCE_ID)


class _Cache:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, timeout=None):
        del timeout
        self.values[key] = value


class _Rendered:
    status_code = 200
    url = 'http://urlbox.invalid/rendered'
    content = b'rendered'

    def iter_content(self, chunk_size):
        del chunk_size
        yield self.content


@pytest.fixture(name='renders')
def fixture_renders(monkeypatch) -> list:
    calls = []

    def get(url, params, stream, timeout):
        del stream, timeout
        calls.append({'url': url, **params})
        return _Rendered()

    monkeypatch.setattr(page_views, 'requests', SimpleNamespace(get=get))
    monkeypatch.setattr(page_views, 'Transaction', _Dashboards)
    monkeypatch.setattr(page_routes, 'Transaction', _Dashboards)
    monkeypatch.setattr(thumbnail_storage_models, 'Transaction', _Dashboards)
    return calls


@pytest.fixture(name='render_app', scope='module')
def fixture_render_app(app: Flask) -> Flask:
    render_app = Flask('tests.authz.render', root_path=_HERE, instance_path=_HERE)
    render_app.zen_config = app.zen_config
    render_app.config.update(
        JWT_SECRET_KEY='tests-authz-render-only',
        JWT_TOKEN_LOCATION=['headers', 'cookies'],
        JWT_ACCESS_COOKIE_NAME='accessKey',
        SERVER_NAME='harmony.invalid',
    )
    JWTManager(render_app)
    render_app.cache = _Cache()

    login_manager = LoginManager(render_app)
    login_manager.anonymous_user = lambda: g.authz_user
    login_manager.request_loader(
        lambda _request: g.authz_user if g.authz_user.is_authenticated else None
    )

    @render_app.before_request
    def load_principal():
        spec = principal_specs()[request.headers[PRINCIPAL_HEADER]]
        g.request_logger = logging.LoggerAdapter(logging.getLogger('tests.authz'), {})
        g.authz_user = StandInUser(spec)
        load_identity(spec)

    dashboard = Blueprint('dashboard', __name__)
    dashboard.add_url_rule('/dashboard/<name>', 'grid_dashboard', lambda name: name)
    render_app.register_blueprint(dashboard)
    render_app.register_blueprint(page_routes.PageRendererRouter().generate_blueprint())

    # A Potion resource class registers with one Api only, and test_potion.py
    # registers the production class; a subclass carries the same route.
    class Storage(thumbnail_storage_models.ThumbnailStorageResource):
        api = None

        class Meta:
            name = 'storage'

    Api(render_app, prefix='/api2').add_resource(Storage)
    return render_app


def _get(render_app, principal, path):
    spec = principal_specs()[principal]
    with configuration(spec.public_access):
        return render_app.test_client().get(path, headers={PRINCIPAL_HEADER: principal})


def _token_claims(render_app, call) -> dict:
    cookie = call['cookie']
    assert cookie.startswith('accessKey=')
    with render_app.app_context():
        return decode_token(cookie[len('accessKey=') :])


# (principal, route, status, rendered as) for render routes, pinned as today.
# `rendered as` is the identity the outbound render token carries, or None
# when no render call is made.
RENDER_ROUTES = [
    ('anonymous', 'png/thumbnail', 200, 'renderbot@authz.invalid'),
    ('role:query_runner', 'png/thumbnail', 200, 'renderbot@authz.invalid'),
    ('anonymous', 'pdf', 401, None),
    ('anonymous', 'jpeg', 401, None),
    ('role:query_runner', 'pdf', 401, None),
    ('role:query_runner', 'jpeg', 401, None),
    ('dashboard_acl_viewer', 'pdf', 200, 'dashboard_acl_viewer@authz.invalid'),
    ('dashboard_acl_viewer', 'jpeg', 200, 'dashboard_acl_viewer@authz.invalid'),
]


@pytest.mark.parametrize(
    'principal,route,status,rendered_as',
    RENDER_ROUTES,
    ids=[f'{p}|{r}|{s}' for p, r, s, _ in RENDER_ROUTES],
)
def test_render_route(principal, route, status, rendered_as, render_app, renders):
    '''N1 (thumbnail rows): defect pinned as today; flips in WP-0i.'''
    response = _get(render_app, principal, f'/dashboard/{SLUG}/{route}')

    assert response.status_code == status
    if rendered_as is None:
        assert renders == []
        return
    (call,) = renders
    claims = _token_claims(render_app, call)
    assert claims['identity'] == rendered_as
    assert claims['user_claims'] == {
        'needs': [['view_resource', RESOURCE_ID, 'dashboard']],
        'query_needs': ['*'],
    }


ATTACKER_URL = 'https://attacker.invalid/steal'


@pytest.mark.parametrize(
    'principal,route,rendered_as',
    [
        ('anonymous', 'png/thumbnail', 'renderbot@authz.invalid'),
        ('dashboard_acl_viewer', 'pdf', 'dashboard_acl_viewer@authz.invalid'),
    ],
)
def test_caller_chosen_url_receives_the_minted_render_token(
    principal, route, rendered_as, render_app, renders
):
    '''WP-0i N7: defect pinned as today; flips in WP-0i. `url` is one of
    SUPPORTED_RENDERING_PARAMS, so a query-string `url` replaces the dashboard
    page in the urlbox call while the cookie still carries the token minted for
    the render.'''
    response = _get(
        render_app, principal, f'/dashboard/{SLUG}/{route}?url={ATTACKER_URL}'
    )

    assert response.status_code == 200
    (call,) = renders
    assert call['url'] == ATTACKER_URL
    assert _token_claims(render_app, call)['identity'] == rendered_as


def test_stored_thumbnail_is_rendered_by_the_render_bot_and_shared(render_app, renders):
    '''N2: defect pinned as today; flips in WP-0i. dashboard_acl_viewer may
    view the dashboard but holds no query policy, so its own queries see no
    rows. Its thumbnail is rendered under the render bot's token with every
    query need and cached on the slug alone, so a second viewer gets the same
    image without a new render.'''
    render_app.cache.values.clear()

    first = _get(
        render_app, 'dashboard_acl_viewer', f'/api2/storage/retrieve?key={SLUG}'
    )
    second = _get(
        render_app, 'role:dashboard_viewer', f'/api2/storage/retrieve?key={SLUG}'
    )

    assert first.status_code == second.status_code == 200
    assert first.get_data() == second.get_data()
    (call,) = renders
    claims = _token_claims(render_app, call)
    assert claims['identity'] == 'renderbot@authz.invalid'
    assert claims['user_claims']['query_needs'] == ['*']
    assert set(render_app.cache.values) == {f'thumbnail_{SLUG}'}


def test_stored_thumbnail_needs_view_on_the_dashboard(render_app, renders):
    render_app.cache.values.clear()
    response = _get(
        render_app, 'role:query_runner', f'/api2/storage/retrieve?key={SLUG}'
    )
    assert response.status_code == 401
    assert renders == []
