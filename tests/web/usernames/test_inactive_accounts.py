"""WP-0k (decision 0010): a deactivated account signs in nowhere.

Before, nothing under `web/` checked a user's status: an account set inactive
kept signing in with its password (a new 365-day token), with the
`X-Username`/`X-Password` headers, and with every token issued before. Now each
path refuses it the way it refuses a bad credential.
"""

import json

import pytest
import sqlalchemy
from flask import session
from flask_login import current_user, login_user
from werkzeug.exceptions import Unauthorized

from models.alchemy.user import UserStatusEnum
from tests.web.usernames.accounts import PASSWORD
from tests.web.usernames.tokens import (
    complete_reset,
    mailed_reset_token,
    api_token,
    login,
    session_token_without_account_id,
    signed_in_id,
)
from web.server.routes.views.authentication import authentication_required
from web.server.util.api_validation import GenericValidationError

JANE = 'jane.doe@moh.gov.rw'  # account 8
TOKEN_ID = 'tok0000008'


def _deactivate(app, user_id=8):
    with app.app_context():
        engine = app.extensions['sqlalchemy'].db.engine
        with engine.begin() as connection:
            connection.execute(
                sqlalchemy.text('UPDATE "user" SET status_id = :status WHERE id = :id'),
                {'status': UserStatusEnum.INACTIVE.value, 'id': user_id},
            )


def _login_error(app, email, password):
    with pytest.raises(GenericValidationError) as raised:
        login(app, email, password)
    return json.dumps(raised.value.errors, default=str)


def test_password_login_refuses_a_deactivated_account_like_a_bad_password(app):
    wrong_password = _login_error(app, JANE, 'not the password')
    _deactivate(app)

    assert _login_error(app, JANE, PASSWORD) == wrong_password


def test_header_login_refuses_a_deactivated_account(app):
    headers = {'X-Username': JANE, 'X-Password': PASSWORD}
    with app.test_request_context('/', headers=headers):
        assert current_user.id == 8
    _deactivate(app)

    with app.test_request_context('/', headers=headers):
        assert not current_user.is_authenticated


@pytest.mark.parametrize('kind', ['session', 'pre-WP-0k session', 'api token'])
def test_a_token_issued_before_deactivation_signs_in_nobody(app, kind):
    if kind == 'session':
        token = login(app, JANE)
    elif kind == 'pre-WP-0k session':
        token = session_token_without_account_id(app, JANE)
    else:
        with app.app_context():
            engine = app.extensions['sqlalchemy'].db.engine
            with engine.begin() as connection:
                connection.execute(
                    sqlalchemy.text(
                        'INSERT INTO api_token (id, user_id, is_revoked) '
                        'VALUES (:id, 8, 0)'
                    ),
                    {'id': TOKEN_ID},
                )
        token = api_token(app, JANE, TOKEN_ID)
    assert signed_in_id(app, token) == 8

    _deactivate(app)

    assert signed_in_id(app, token) is None


def test_a_login_session_cookie_signs_in_nobody_once_deactivated(app):
    with app.test_request_context('/'):
        session['user_id'] = '8'  # flask-login 0.4
        assert current_user.id == 8
    _deactivate(app)

    with app.test_request_context('/'):
        session['user_id'] = '8'  # flask-login 0.4
        assert not current_user.is_authenticated


def test_authentication_required_refuses_a_deactivated_account(app, monkeypatch):
    # pylint: disable=import-outside-toplevel
    from web.server.routes.views import authentication

    monkeypatch.setattr(authentication, 'get_configuration', lambda key: False)

    @authentication_required(is_api_request=True)
    def protected():
        return 'reached'

    _deactivate(app)
    with app.test_request_context('/'):
        user = app.user_manager.db_adapter.get_object(
            app.user_manager.db_adapter.UserClass, 8
        )
        login_user(user, force=True)
        with pytest.raises(Unauthorized):
            protected()


NEW_PASSWORD = 'a new password 2B!'


def _complete_reset(app, user_id):
    '''`POST /api2/authentication/reset_password` with the token a mail carries.'''
    return complete_reset(app, mailed_reset_token(app, user_id), NEW_PASSWORD)


def _status(app, user_id):
    with app.app_context():
        engine = app.extensions['sqlalchemy'].db.engine
        with engine.connect() as connection:
            return connection.execute(
                sqlalchemy.text('SELECT status_id FROM "user" WHERE id = :id'),
                {'id': user_id},
            ).scalar()


def test_a_pending_account_completing_a_reset_is_activated(app):
    '''An invitee who follows a reset link an admin sent, rather than the
    invitation, sets a password and becomes active, as registering would.'''
    response = _complete_reset(app, 4)

    assert response.status_code == 200
    assert _status(app, 4) == UserStatusEnum.ACTIVE.value
    assert signed_in_id(app, login(app, 'Pending.User@moh.gov.rw', NEW_PASSWORD)) == 4


def test_a_deactivated_account_cannot_complete_a_reset(app):
    _deactivate(app)

    with pytest.raises(GenericValidationError) as raised:
        _complete_reset(app, 8)

    assert 'invalid_reset_link' in json.dumps(raised.value.errors, default=str)
    assert _status(app, 8) == UserStatusEnum.INACTIVE.value


def test_a_pending_twin_of_an_active_account_cannot_complete_a_reset(app):
    with pytest.raises(GenericValidationError):
        _complete_reset(app, 11)

    assert _status(app, 11) == UserStatusEnum.PENDING.value


def test_flask_user_finds_accounts_of_every_status(app, request_ctx):
    '''flask-user's own reset and confirm views look accounts up by id; only
    signing in checks the status.'''
    _deactivate(app)

    assert app.user_manager.get_user_by_id(8).id == 8
    assert app.user_manager.get_user_by_id(4).id == 4


def test_a_deactivated_account_is_refused_after_the_password_check(
    app, request_ctx, monkeypatch
):
    '''Checking the status first answered in a few milliseconds instead of a
    bcrypt verification's time, telling an attacker the account is
    deactivated.'''
    # pylint: disable=import-outside-toplevel
    from web.server.routes.views.authentication import try_authenticate_user

    checked = []
    verify = app.user_manager.verify_password
    monkeypatch.setattr(
        app.user_manager,
        'verify_password',
        lambda password, user: checked.append(user.id) or verify(password, user),
    )
    _deactivate(app)

    assert try_authenticate_user(JANE, PASSWORD) is None
    assert checked == [8]
