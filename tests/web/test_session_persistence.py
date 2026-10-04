from __future__ import annotations

from datetime import timedelta
from http.cookies import SimpleCookie

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from web.server.util.authentication import is_session_persisted, login_user

USERNAME = 'analyst@example.org'


@pytest.fixture(name='app_signing_with')
def fixture_app_signing_with(bare_flask_app):
    def build(jwt_secret_key: str) -> Flask:
        app = bare_flask_app()
        # The JWT settings that matter here, as in web/server/configuration/flask.py.
        app.config.update(
            JWT_SECRET_KEY=jwt_secret_key,
            JWT_TOKEN_LOCATION=['headers', 'cookies'],
            JWT_ACCESS_COOKIE_NAME='accessKey',
            JWT_CSRF_METHODS=[],
            JWT_TOKEN_WEB_COOKIE_EXPIRATION=timedelta(days=365),
        )
        JWTManager(app)
        return app

    return build


@pytest.fixture(name='app')
def fixture_app(app_signing_with) -> Flask:
    return app_signing_with('tests-web-placeholder-jwt-key')


def _cookie_header_after_login(
    app: Flask, remember_me: bool, expires: timedelta | None = None
) -> str:
    with app.test_request_context('/api/login', method='POST'):
        response = login_user('login_successful', USERNAME, remember_me, expires)
    jar: SimpleCookie = SimpleCookie()
    for header in response.headers.getlist('Set-Cookie'):
        jar.load(header)
    return '; '.join(f'{name}={morsel.value}' for name, morsel in jar.items())


def _persisted(app: Flask, cookie_header: str = '', **headers: str) -> bool:
    if cookie_header:
        headers['Cookie'] = cookie_header
    with app.test_request_context('/', headers=headers):
        return is_session_persisted()


def test_remember_me_login_is_persisted(app):
    assert _persisted(app, _cookie_header_after_login(app, remember_me=True))


def test_login_without_remember_me_is_not_persisted(app):
    assert not _persisted(app, _cookie_header_after_login(app, remember_me=False))


def test_no_access_cookie_is_not_persisted(app):
    assert not _persisted(app)


def test_flask_login_remember_cookie_alone_is_not_persisted(app):
    assert not _persisted(app, 'remember_token=1|deadbeef')


def test_garbage_access_cookie_is_not_persisted(app):
    assert not _persisted(app, 'accessKey=not-a-jwt')


def test_access_cookie_signed_with_another_key_is_not_persisted(app, app_signing_with):
    cookie_header = _cookie_header_after_login(app, remember_me=True)
    assert not _persisted(
        app_signing_with('a-different-placeholder-key'), cookie_header
    )


def test_expired_remember_me_token_is_not_persisted(app):
    cookie_header = _cookie_header_after_login(
        app, remember_me=True, expires=timedelta(seconds=-60)
    )
    assert not _persisted(app, cookie_header)


def test_bearer_token_without_the_claim_wins_over_a_remembered_cookie(app):
    # Authentication reads the header before the cookie, so persistence must too.
    remembered_cookie = _cookie_header_after_login(app, remember_me=True)
    with app.app_context():
        api_token = create_access_token(identity=USERNAME)
    assert not _persisted(app, remembered_cookie, Authorization=f'Bearer {api_token}')
