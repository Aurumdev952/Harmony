"""A Flask app with the production URL rules that mailed links point at, the
real `EmailRenderer`, and a mailer that records what would be sent.

Only the edges are faked: the database lookups, the token generator and the
outbound mail.
"""

import os

import pytest
from flask import Flask, request
from flask_login import LoginManager

from config.loader import import_configuration_module
from tests.web.links.support import (
    ORIGIN,
    USERS,
    FakeUserManager,
    RecordingMailer,
)
from web.server.routes.dashboard import DashboardPageRouter
from web.server.routes.index import PageRouter
from web.server.routes.user_authentication import UserAuthenticationRouter
from web.server.util.emails import EmailRenderer


def _page():
    return ''


@pytest.fixture(name='app', scope='session')
def fixture_app() -> Flask:
    here = os.path.dirname(__file__)
    app = Flask('tests.web.links', root_path=here, instance_path=here)
    app.config.update(TESTING=True, USER_RESET_PASSWORD_EXPIRATION=2 * 24 * 3600)
    app.zen_config = import_configuration_module('harmony_demo')

    login_manager = LoginManager(app)

    @login_manager.request_loader
    def _load_user(_request):
        return USERS.get(request.headers.get('X-Test-User', ''))

    # The production routers each mailed link is built for, and flask-user's
    # register rule as UserManager adds it from USER_REGISTER_URL.
    app.register_blueprint(UserAuthenticationRouter(None, 'en').generate_blueprint())
    app.register_blueprint(DashboardPageRouter(None, 'en').generate_blueprint())
    app.register_blueprint(PageRouter(None, 'en', 'demo', None).generate_blueprint())
    app.add_url_rule('/zen/register', 'user.register', _page)
    return app


@pytest.fixture(name='mailer')
def fixture_mailer(app: Flask, monkeypatch) -> RecordingMailer:
    general = app.zen_config.general
    monkeypatch.setattr(general, 'DEPLOYMENT_BASE_URL', ORIGIN)
    renderer = EmailRenderer(
        'en',
        general.DEPLOYMENT_NAME,
        general.DEPLOYMENT_FULL_NAME,
        general.DEPLOYMENT_SHORT_NAME,
        ORIGIN,
        app.zen_config.ui.FULL_PLATFORM_NAME,
    )
    monkeypatch.setattr(renderer, 'get_project_managers', lambda: [])
    mailer = RecordingMailer()
    monkeypatch.setattr(app, 'email_renderer', renderer, raising=False)
    monkeypatch.setattr(app, 'notification_service', mailer, raising=False)
    monkeypatch.setattr(app, 'user_manager', FakeUserManager(), raising=False)
    return mailer
