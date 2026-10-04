from datetime import timedelta
from http.cookies import SimpleCookie

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager

from web.server.util.authentication import login_user
from web.server.util.util import is_session_persisted


@pytest.fixture(name='app_signing_with')
def fixture_app_signing_with(bare_flask_app):
    def build(jwt_secret_key: str) -> Flask:
        app = bare_flask_app()
        app.config.update(
            JWT_SECRET_KEY=jwt_secret_key,
            JWT_TOKEN_WEB_COOKIE_EXPIRATION=timedelta(days=365),
        )
        JWTManager(app)
        return app

    return build


@pytest.fixture(name='app')
def fixture_app(app_signing_with) -> Flask:
    return app_signing_with('tests-web-placeholder-jwt-key')


def _cookie_header_after_login(app: Flask, remember_me: bool) -> str:
    with app.test_request_context('/api/login', method='POST'):
        response = login_user('login_successful', 'analyst@example.org', remember_me)
    jar: SimpleCookie = SimpleCookie()
    for header in response.headers.getlist('Set-Cookie'):
        jar.load(header)
    return '; '.join(f'{name}={morsel.value}' for name, morsel in jar.items())


def _persisted(app: Flask, cookie_header: str) -> bool:
    with app.test_request_context('/', headers={'Cookie': cookie_header}):
        return is_session_persisted()


def test_remember_me_login_is_persisted(app):
    assert _persisted(app, _cookie_header_after_login(app, remember_me=True))


def test_login_without_remember_me_is_not_persisted(app):
    assert not _persisted(app, _cookie_header_after_login(app, remember_me=False))


def test_no_access_cookie_is_not_persisted(app):
    assert not _persisted(app, '')


def test_flask_login_remember_cookie_alone_is_not_persisted(app):
    assert not _persisted(app, 'remember_token=1|deadbeef')


def test_access_cookie_signed_with_another_key_is_not_persisted(app, app_signing_with):
    cookie_header = _cookie_header_after_login(app, remember_me=True)
    assert not _persisted(
        app_signing_with('a-different-placeholder-key'), cookie_header
    )
