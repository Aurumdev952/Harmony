"""A Flask app with the production URL rules that mailed links point at, the
real `EmailRenderer`, and a mailer that records what would be sent.

Only the edges are faked: the database lookups, the token generator and the
outbound mail.
"""

import os

import pytest
from flask import Blueprint, Flask, request
from flask_login import LoginManager

from config.loader import import_configuration_module
from tests.web.links.support import (
    ORIGIN,
    USERS,
    FakeUserManager,
    RecordingMailer,
)
from web.server.routes.user_authentication import UserAuthenticationRouter
from web.server.util.emails import EmailRenderer


def _page(**_kwargs):
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

    # The production rules each mailed link is built for.
    app.register_blueprint(UserAuthenticationRouter(None, 'en').generate_blueprint())
    user = Blueprint('user', __name__)
    user.add_url_rule('/zen/register', 'register', _page)  # USER_REGISTER_URL
    app.register_blueprint(user)
    dashboard = Blueprint('dashboard', __name__)
    dashboard.add_url_rule('/dashboard/<name>', 'grid_dashboard', _page)
    dashboard.add_url_rule('/<locale>/dashboard/<name>', 'grid_dashboard', _page)
    app.register_blueprint(dashboard)
    index = Blueprint('index', __name__)
    index.add_url_rule('/advanced-query', 'advanced_query', _page)
    index.add_url_rule('/<locale>/advanced-query', 'advanced_query', _page)
    app.register_blueprint(index)
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
