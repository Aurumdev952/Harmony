'''The dashboard render routes (web/server/routes/page_renderer.py) and the
thumbnail store (/api2/storage/retrieve), run in-process.

The outbound render call (`requests.post` to the renderer service) is replaced
by a recorder. The database lookups of a dashboard by slug
are replaced by a fixed dashboard, Resource.id 7.
'''

from __future__ import annotations

import logging
import os
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

import pytest
import requests
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
from web.server.routes.views import authentication as authentication_views
from web.server.routes.views import dashboard as dashboard_views
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

    def add(self, key, value, timeout=None):
        del timeout
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key):
        self.values.pop(key, None)


class _Rendered:
    status_code = 200
    content = b'rendered'

    def __init__(self, content_type):
        self.headers = {'Content-Type': content_type}

    def iter_content(self, chunk_size):
        del chunk_size
        yield self.content

    def close(self):
        pass


@pytest.fixture(name='renders')
def fixture_renders(monkeypatch) -> list:
    calls = []

    def post(url, json, timeout, stream):
        del url, stream, timeout
        calls.append({**json, 'cookie': 'accessKey=' + json['token']})
        return _Rendered(page_views.CONTENT_TYPES[json['format']])

    monkeypatch.setattr(
        page_views,
        'requests',
        SimpleNamespace(post=post, RequestException=requests.RequestException),
    )
    monkeypatch.setattr(page_views, 'Transaction', _Dashboards)
    monkeypatch.setattr(
        dashboard_views,
        'get_dashboard',
        lambda slug, session=None: (
            SimpleNamespace(slug=SLUG, resource_id=RESOURCE_ID)
            if slug == SLUG
            else None
        ),
    )
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


def _get(render_app, principal, path, headers=None):
    spec = principal_specs()[principal]
    # ExitStack, not a parenthesised `with`: the web image runs Python 3.8.
    with ExitStack() as stack:
        stack.enter_context(configuration(spec.public_access))
        stack.enter_context(
            mock.patch.object(
                authentication_views,
                'get_configuration',
                lambda key: spec.public_access,
            )
        )
        return render_app.test_client().get(
            path, headers={PRINCIPAL_HEADER: principal, **(headers or {})}
        )


def _token_claims(render_app, call) -> dict:
    cookie = call['cookie']
    assert cookie.startswith('accessKey=')
    with render_app.app_context():
        return decode_token(cookie[len('accessKey=') :])


RENDER_ROUTES = [
    ('anonymous', 'png/thumbnail', 401, None),
    ('anonymous_public', 'png/thumbnail', 401, None),
    ('role:query_runner', 'png/thumbnail', 403, None),
    (
        'dashboard_acl_viewer',
        'png/thumbnail',
        200,
        'dashboard_acl_viewer@authz.invalid',
    ),
    ('anonymous', 'pdf', 401, None),
    ('anonymous_public', 'pdf', 401, None),
    ('anonymous', 'jpeg', 401, None),
    ('role:query_runner', 'pdf', 403, None),
    ('role:query_runner', 'jpeg', 403, None),
    ('dashboard_acl_viewer', 'pdf', 200, 'dashboard_acl_viewer@authz.invalid'),
    ('dashboard_acl_viewer', 'jpeg', 200, 'dashboard_acl_viewer@authz.invalid'),
    ('role:admin', 'pdf', 200, 'role:admin@authz.invalid'),
]


@pytest.mark.parametrize(
    'principal,route,status,rendered_as',
    RENDER_ROUTES,
    ids=[f'{p}|{r}|{s}' for p, r, s, _ in RENDER_ROUTES],
)
def test_render_route(principal, route, status, rendered_as, render_app, renders):
    response = _get(render_app, principal, f'/dashboard/{SLUG}/{route}')

    assert response.status_code == status
    if rendered_as is None:
        assert renders == []
        return
    (call,) = renders
    claims = _token_claims(render_app, call)
    assert claims['identity'] == rendered_as
    user_claims = dict(claims['user_claims'])
    assert set(user_claims) - {'needs', 'query_needs'} <= {'render', 'policy'}
    assert {k: user_claims[k] for k in ('needs', 'query_needs')} == {
        'needs': [['view_resource', RESOURCE_ID, 'dashboard']],
        'query_needs': ['*'],
    }


ATTACKER_URL = 'https://attacker.invalid/steal'


@pytest.mark.parametrize(
    'principal,path,rendered_as',
    [
        (
            'dashboard_acl_viewer',
            f'/dashboard/{SLUG}/png/thumbnail',
            'dashboard_acl_viewer@authz.invalid',
        ),
        (
            'dashboard_acl_viewer',
            f'/dashboard/{SLUG}/pdf',
            'dashboard_acl_viewer@authz.invalid',
        ),
        (
            'role:admin',
            f'/api2/storage/retrieve?key={SLUG}',
            'role:admin@authz.invalid',
        ),
    ],
)
def test_caller_chosen_url_does_not_receive_the_minted_render_token(
    principal, path, rendered_as, render_app, renders
):
    '''WP-0i N7, flipped: `url` and `cookie` are no longer passed through to
    urlbox, so the minted token only goes to this deployment's own dashboard
    page on its configured DEPLOYMENT_BASE_URL.'''
    render_app.cache.values.clear()
    separator = '&' if '?' in path else '?'
    response = _get(
        render_app,
        principal,
        f'{path}{separator}url={ATTACKER_URL}&cookie=accessKey=planted',
    )

    assert response.status_code == 200
    (call,) = renders
    assert call['url'].startswith(f'{page_views.RENDER_WEB_ORIGIN}/dashboard/{SLUG}?')
    assert _token_claims(render_app, call)['identity'] == rendered_as


def test_stored_thumbnail_is_rendered_as_each_policy_holder(render_app, renders):
    render_app.cache.values.clear()

    admin = _get(render_app, 'role:admin', f'/api2/storage/retrieve?key={SLUG}')
    viewer = _get(
        render_app, 'dashboard_acl_viewer', f'/api2/storage/retrieve?key={SLUG}'
    )
    group_viewer = _get(
        render_app, 'group_acl_viewer', f'/api2/storage/retrieve?key={SLUG}'
    )

    assert admin.status_code == viewer.status_code == group_viewer.status_code == 200
    identities = [_token_claims(render_app, call)['identity'] for call in renders]
    assert identities == [
        'role:admin@authz.invalid',
        'dashboard_acl_viewer@authz.invalid',
    ]
    assert len(render_app.cache.values) == 2
    assert all(key.startswith('thumbnail:v2:7:') for key in render_app.cache.values)


def test_stored_thumbnail_needs_view_on_the_dashboard(render_app, renders):
    render_app.cache.values.clear()
    response = _get(
        render_app, 'role:query_runner', f'/api2/storage/retrieve?key={SLUG}'
    )
    assert response.status_code == 403
    assert renders == []


def test_stored_thumbnail_needs_a_signed_in_caller_under_public_access(
    render_app, renders
):
    render_app.cache.values.clear()
    response = _get(
        render_app,
        'anonymous_public',
        f'/api2/storage/retrieve?key={SLUG}',
        headers={'Referer': 'http://harmony.invalid/overview'},
    )
    assert response.status_code == 401
    assert renders == []
