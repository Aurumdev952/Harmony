from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest import mock

import pytest
from flask import Flask, jsonify
from flask.testing import FlaskClient
from flask_jwt_extended import JWTManager
from flask_login import LoginManager, UserMixin, current_user

from web.server.configuration.settings import AUTOMATIC_SIGN_OUT_KEY
from web.server.routes.api import ApiRouter
from web.server.security.signal_handlers import install_login_manager_signal_handlers
from web.server.util.authentication import login_user

USERNAME = 'analyst@example.org'


class _User(UserMixin):
    id = USERNAME


@contextmanager
def _users_table():
    def find_one_by_fields(_model, _case_sensitive, fields):
        return _User() if fields == {'username': USERNAME} else None

    yield SimpleNamespace(find_one_by_fields=find_one_by_fields)


@pytest.fixture(name='app')
def fixture_app(bare_flask_app) -> Flask:
    app = bare_flask_app()
    app.config.update(
        SECRET_KEY='tests-web-placeholder-session-key',
        JWT_SECRET_KEY='tests-web-placeholder-jwt-key',
        JWT_TOKEN_LOCATION=['headers', 'cookies'],
        JWT_ACCESS_COOKIE_NAME='accessKey',
        JWT_CSRF_METHODS=[],
        JWT_TOKEN_WEB_COOKIE_EXPIRATION=timedelta(days=365),
    )
    JWTManager(app)
    app.cache = SimpleNamespace(memoize=lambda: lambda function: function)
    login_manager = LoginManager(app)

    # A session id signs the user in first (Flask-User's loader in the app).
    @login_manager.user_loader
    def load_user(user_id):
        return _User() if user_id == USERNAME else None

    # Then the app's own loader: the JWT from the header or the accessKey cookie.
    install_login_manager_signal_handlers(app, login_manager)

    app.register_blueprint(ApiRouter(None, None).generate_blueprint())
    app.add_url_rule(
        '/whoami', 'whoami', lambda: jsonify(current_user.is_authenticated)
    )
    return app


@pytest.fixture(autouse=True)
def fixture_users_table():
    with mock.patch('web.server.security.signal_handlers.Transaction', _users_table):
        yield


def _signed_in_client(app: Flask, remember_me: bool) -> FlaskClient:
    with app.test_request_context('/api/login', method='POST'):
        response = login_user('login_successful', USERNAME, remember_me)
    client = app.test_client()
    for header in response.headers.getlist('Set-Cookie'):
        for name, morsel in SimpleCookie(header).items():
            client.set_cookie('localhost', name, morsel.value)
    return client


def _timeout(client: FlaskClient, automatic_sign_out: bool = True):
    with mock.patch(
        'web.server.routes.api.get_configuration',
        lambda key: automatic_sign_out if key == AUTOMATIC_SIGN_OUT_KEY else None,
    ):
        return client.post('/api/timeout')


def _cleared_cookies(response) -> set[str]:
    cleared = set()
    for header in response.headers.getlist('Set-Cookie'):
        for name, morsel in SimpleCookie(header).items():
            if not morsel.value and '1970' in morsel['expires']:
                cleared.add(name)
    return cleared


def test_timeout_clears_the_access_cookie_and_signs_the_user_out(app):
    client = _signed_in_client(app, remember_me=False)
    assert client.get('/whoami').get_json() is True

    response = _timeout(client)

    assert response.get_json() == {'data': {'timeout': True}}
    assert 'accessKey' in _cleared_cookies(response)
    # The 365-day accessKey used to sign the user straight back in.
    assert client.get('/whoami').get_json() is False


def test_timeout_ends_a_flask_login_session(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = USERNAME
    assert client.get('/whoami').get_json() is True

    assert _timeout(client).get_json() == {'data': {'timeout': True}}
    assert client.get('/whoami').get_json() is False


def test_remembered_session_is_not_timed_out(app):
    client = _signed_in_client(app, remember_me=True)

    response = _timeout(client)

    assert response.get_json() == {'data': {'timeout': False}}
    assert not _cleared_cookies(response)
    assert client.get('/whoami').get_json() is True


def test_disabled_automatic_sign_out_leaves_the_session_alone(app):
    client = _signed_in_client(app, remember_me=False)

    response = _timeout(client, automatic_sign_out=False)

    assert response.get_json() == {'data': {'timeout': False}}
    assert not _cleared_cookies(response)
    assert client.get('/whoami').get_json() is True
