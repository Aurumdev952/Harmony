import os

import jwt
import pytest
from flask_caching import Cache
from flask_jwt_extended import create_access_token
from flask_login import LoginManager

# config/settings.py reads these at import time; the values are test-only placeholders.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-web-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('ZEN_ENV', 'harmony_demo')

# pylint: disable=wrong-import-position
from config import settings
from web.server.app import initialize_jwt_manager
from web.server.app_base import create_bare_app
from web.server.configuration.flask import FlaskConfiguration
from web.server.security.signal_handlers import install_login_manager_signal_handlers

JWT_KEY = 'tests-web-jwt-key'


@pytest.fixture(name='key_env')
def fixture_key_env(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.delenv('JWT_SECRET_KEY', raising=False)
    return monkeypatch


def test_session_key_cannot_be_overridden_past_the_checked_key(key_env):
    # SECRET_KEY used to override DEFAULT_SECRET_KEY unchecked, so SECRET_KEY=changeme
    # would have bypassed the refusal in config/settings.py.
    key_env.setenv('SECRET_KEY', 'changeme')

    assert FlaskConfiguration().SECRET_KEY == settings.DEFAULT_SECRET_KEY


def test_access_tokens_are_signed_with_the_jwt_key_only(key_env):
    key_env.setenv('JWT_SECRET_KEY', JWT_KEY)
    app = create_bare_app(FlaskConfiguration())
    initialize_jwt_manager(app)

    with app.app_context():
        token = create_access_token(identity='someone@example.org')

    assert jwt.decode(token, JWT_KEY, algorithms=['HS256'])['identity'] == (
        'someone@example.org'
    )
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, settings.DEFAULT_SECRET_KEY, algorithms=['HS256'])


@pytest.mark.parametrize(
    'jwt_key',
    [None, '', '   ', 'changeme', ' ChangeMe ', settings.DEFAULT_SECRET_KEY],
    ids=['unset', 'empty', 'blank', 'changeme', 'changeme-mixed-case', 'secret-key'],
)
def test_refuses_to_start_with_an_unusable_jwt_key(key_env, jwt_key):
    if jwt_key is not None:
        key_env.setenv('JWT_SECRET_KEY', jwt_key)
    app = create_bare_app(FlaskConfiguration())

    with pytest.raises(RuntimeError, match='JWT_SECRET_KEY'):
        initialize_jwt_manager(app)


def test_cookie_signed_with_the_old_key_is_anonymous_not_an_error(key_env):
    # Before the split, accessKey cookies (365 days) and API tokens were signed with
    # DEFAULT_SECRET_KEY. After deploy they must send the user to the login page
    # rather than fail every request, including /login, with a signature error.
    key_env.setenv('JWT_SECRET_KEY', JWT_KEY)
    app = create_bare_app(FlaskConfiguration())
    initialize_jwt_manager(app)
    app.cache = Cache(app, config={'CACHE_TYPE': 'NullCache'})
    login_manager = LoginManager(app)
    install_login_manager_signal_handlers(app, login_manager)
    old_token = jwt.encode(
        {'identity': 'someone@example.org', 'type': 'access', 'jti': 'old'},
        settings.DEFAULT_SECRET_KEY,
        algorithm='HS256',
    ).decode()

    with app.test_request_context(headers={'Cookie': f'accessKey={old_token}'}):
        assert login_manager.request_callback() is None


@pytest.mark.usefixtures('key_env')
def test_scripts_build_a_config_without_a_jwt_key():
    # Pipeline scripts build a FlaskConfiguration for its database URL and never
    # issue or verify tokens, so they must not need the JWT key.
    assert FlaskConfiguration().SECRET_KEY == settings.DEFAULT_SECRET_KEY
