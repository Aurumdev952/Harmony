"""A minimal Flask app that mounts the real render blueprint and the real
`/api2/storage/retrieve` resource behind the same Potion decorator as
`web/server/app.py`. Only the edges are faked (`tests/web/render/fakes.py`): the
dashboard table, the configuration store, the cache, the login loader and the
outbound urlbox call.
"""

import dataclasses
import logging
import os
from typing import Iterator

import pytest

# Test-only placeholders read at import time by config modules.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-web-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('ZEN_ENV', 'harmony_demo')

# pylint: disable=wrong-import-position
from flask import Blueprint, Flask, g, request
from flask_jwt_extended import (
    JWTManager,
    get_jwt_identity,
    verify_jwt_in_request_optional,
)
from flask_login import LoginManager, current_user
from flask_potion import Api
from flask_principal import AnonymousIdentity, Identity, Principal, identity_loaded

from config.loader import import_configuration_module
from tests.web.render.fakes import (
    DEPLOYMENT_ORIGIN,
    PUBLIC_ACCESS,
    USERS,
    VIEW_DASHBOARD,
    DictCache,
    FakeRenderer,
    FakeTransaction,
    fake_get_dashboard,
)
from web.server.api.thumbnail_storage_models import ThumbnailStorageResource
from web.server.routes.page_renderer import PageRendererRouter
from web.server.routes.views import authentication
from web.server.routes.views import dashboard as dashboard_views
from web.server.routes.views import page_renderer as page_renderer_views
from web.server.routes.views.authentication import authentication_required
from web.server.security import permissions, signal_handlers


@pytest.fixture(name='app', scope='session')
def fixture_app() -> Flask:
    """Session-scoped because Potion binds a resource class to a single `Api`."""
    here = os.path.dirname(__file__)
    app = Flask('tests.web', root_path=here, instance_path=here)
    app.config.update(
        TESTING=True,
        JWT_SECRET_KEY='tests-web-jwt-placeholder',
        JWT_TOKEN_LOCATION=['headers', 'cookies'],
        JWT_ACCESS_COOKIE_NAME='accessKey',
    )
    JWTManager(app)
    app.zen_config = import_configuration_module('harmony_demo')

    # Registered before Principal's own hook, which loads the identity and logs.
    @app.before_request
    def _request_logger():
        g.request_logger = logging.LoggerAdapter(logging.getLogger('tests.web'), {})

    login_manager = LoginManager(app)

    @login_manager.request_loader
    def _load_user(_request):
        # An accessKey cookie signs its user in, as `login_from_request` does.
        verify_jwt_in_request_optional()
        jwt_user = USERS.get(get_jwt_identity() or '')
        if jwt_user:
            return dataclasses.replace(jwt_user, from_jwt=True)
        return USERS.get(request.headers.get('X-Test-User', ''))

    principals = Principal(app, use_sessions=False)

    @principals.identity_loader
    def _load_identity():
        if current_user.is_authenticated:
            return Identity(current_user.id)
        return AnonymousIdentity()

    @identity_loaded.connect_via(app)
    def _on_identity_loaded(sender, identity):
        if getattr(current_user, 'from_jwt', False):
            signal_handlers.on_identity_loaded(sender, identity)
        elif current_user.is_authenticated:
            identity.provides |= set(current_user.provides)
        elif PUBLIC_ACCESS['enabled']:
            identity.provides.add(VIEW_DASHBOARD)

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

    # Other suites register the production class with their own Api; a Potion
    # resource class binds to one Api, so this app serves a subclass.
    class Storage(ThumbnailStorageResource):
        api = None

        class Meta:
            name = 'storage'

    api = Api(
        app, decorators=[authentication_required(is_api_request=True)], prefix='/api2'
    )
    api.add_resource(Storage)
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
    monkeypatch.setattr(page_renderer_views, 'Transaction', FakeTransaction)
    monkeypatch.setattr(dashboard_views, 'get_dashboard', fake_get_dashboard)
    monkeypatch.setattr(
        app.zen_config.general, 'DEPLOYMENT_BASE_URL', DEPLOYMENT_ORIGIN
    )

    monkeypatch.setattr(app, 'cache', DictCache(), raising=False)
    renderer = FakeRenderer(app)
    monkeypatch.setattr(page_renderer_views, 'requests', renderer)
    return renderer


@pytest.fixture(name='client')
def fixture_client(app: Flask, renderer: FakeRenderer):
    return app.test_client()
