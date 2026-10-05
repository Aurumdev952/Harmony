'''POST /api2/authentication/register must only accept a live invitation.

The route is anonymous, so the invite token is the only credential. Every
account starts with reset_password_token = '' (the column default), so an empty
token used to match any account that had never been invited or reset.
'''

import importlib
import os
import pkgutil
from datetime import timedelta
from types import SimpleNamespace

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager
from flask_potion import Api

import models.alchemy
from models.alchemy.user import User, UserStatus, UserStatusEnum
from web.server.api.authentication_api_models import AuthenticationResource
from web.server.app_db import create_db

EMAIL = 'victim@example.org'
OLD_HASH = 'old-hash'
NEW_PASSWORD = 'attacker-password'
INVITE_TOKEN = 'live-invite-token'

# User's relationships only configure once every model is registered.
for _module in pkgutil.iter_modules(models.alchemy.__path__):
    importlib.import_module(f'models.alchemy.{_module.name}')


@pytest.fixture(name='app', scope='module')
def fixture_app():
    here = os.path.dirname(__file__)
    app = Flask('tests.web', root_path=here, instance_path=here)
    app.config.update(
        SQLALCHEMY_DATABASE_URI='sqlite://',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY='tests-web-placeholder-key',
        JWT_ACCESS_COOKIE_NAME='accessKey',
        JWT_TOKEN_WEB_COOKIE_EXPIRATION=timedelta(hours=1),
    )
    db = create_db()
    db.init_app(app)
    JWTManager(app)
    app.user_manager = SimpleNamespace(
        hash_password=lambda password: 'hashed:' + password
    )
    # Potion lets a resource join only one Api, hence the module scope.
    Api(app, prefix='/api2').add_resource(AuthenticationResource)

    with app.app_context():
        db.Model.metadata.create_all(
            db.engine, tables=[UserStatus.__table__, User.__table__]
        )
        db.session.add_all(UserStatus(id=s.value, status=s) for s in UserStatusEnum)
        db.session.commit()
        yield app


@pytest.fixture(autouse=True)
def fixture_empty_user_table(app):
    yield
    db = app.extensions['sqlalchemy'].db
    db.session.rollback()
    db.session.query(User).delete()
    db.session.commit()


def _add_user(app, status, token):
    db = app.extensions['sqlalchemy'].db
    db.session.add(
        User(
            username=EMAIL,
            password=OLD_HASH,
            reset_password_token=token,
            status_id=status.value,
        )
    )
    db.session.commit()


def _register(app, token, email=EMAIL):
    return app.test_client().post(
        '/api2/authentication/register',
        json={
            'email': email,
            'firstname': 'Eve',
            'lastname': 'Attacker',
            'password': NEW_PASSWORD,
            'invite_token': token,
        },
    )


def _stored_user(app):
    db = app.extensions['sqlalchemy'].db
    db.session.expire_all()
    return db.session.query(User).filter_by(username=EMAIL).one()


def _assert_refused(app, response, token, status):
    assert response.status_code == 400
    assert 'accessKey' not in response.headers.get('Set-Cookie', '')
    user = _stored_user(app)
    assert user.password == OLD_HASH
    assert user.status_id == status.value
    assert user.reset_password_token == token


@pytest.mark.parametrize('token', ['', ' ', '\t\n'])
def test_empty_token_cannot_take_over_never_invited_account(app, token):
    _add_user(app, UserStatusEnum.ACTIVE, '')

    response = _register(app, token)

    _assert_refused(app, response, '', UserStatusEnum.ACTIVE)


def test_empty_token_cannot_register_pending_account_without_token(app):
    _add_user(app, UserStatusEnum.PENDING, '')

    response = _register(app, '')

    _assert_refused(app, response, '', UserStatusEnum.PENDING)


def test_wrong_token_is_refused(app):
    _add_user(app, UserStatusEnum.PENDING, INVITE_TOKEN)

    response = _register(app, 'some-other-token')

    _assert_refused(app, response, INVITE_TOKEN, UserStatusEnum.PENDING)


def test_token_for_a_different_email_is_refused(app):
    _add_user(app, UserStatusEnum.PENDING, INVITE_TOKEN)

    response = _register(app, INVITE_TOKEN, email='someone-else@example.org')

    _assert_refused(app, response, INVITE_TOKEN, UserStatusEnum.PENDING)


@pytest.mark.parametrize('status', [UserStatusEnum.ACTIVE, UserStatusEnum.INACTIVE])
def test_live_token_cannot_register_an_account_that_is_not_pending(app, status):
    # An active account holds a token after a password-reset request; an
    # inactive one may still hold an old invitation.
    _add_user(app, status, INVITE_TOKEN)

    response = _register(app, INVITE_TOKEN)

    _assert_refused(app, response, INVITE_TOKEN, status)


def test_pending_invitee_registers_once_and_is_signed_in(app):
    _add_user(app, UserStatusEnum.PENDING, INVITE_TOKEN)

    response = _register(app, INVITE_TOKEN)

    assert response.status_code == 200
    assert response.get_json() == {'msg': 'registration_successful'}
    assert 'accessKey=' in response.headers['Set-Cookie']
    user = _stored_user(app)
    assert user.password == 'hashed:' + NEW_PASSWORD
    assert user.status_id == UserStatusEnum.ACTIVE.value
    assert user.reset_password_token == ''

    replay = _register(app, INVITE_TOKEN)

    assert replay.status_code == 400
    assert 'accessKey' not in replay.headers.get('Set-Cookie', '')
