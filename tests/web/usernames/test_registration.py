'''WP-0k: registration completes an invitation, and nothing else.

`POST /api2/authentication/register` found the account by its
`reset_password_token` alone, and that column defaults to the empty string. An
empty token with the username of any account that never had a reset set that
account's password, activated it and signed the caller in. A forgot-password
token or an old invitation did the same for an account of any status, so a
deactivated account could reactivate itself.
'''

import pytest
import sqlalchemy
from werkzeug.exceptions import BadRequest

from models.alchemy.user import UserStatusEnum
from tests.web.usernames.tokens import signed_in_id
from web.server.api.authentication_api_models import AuthenticationResource

NEW_PASSWORD = 'a new password 2B!'
JANE = 'jane.doe@moh.gov.rw'  # account 8, active, no reset token


def _run(app, sql, **params):
    with app.app_context():
        engine = app.extensions['sqlalchemy'].db.engine
        with engine.begin() as connection:
            connection.execute(sqlalchemy.text(sql), params)


def _row(app, user_id):
    with app.app_context():
        engine = app.extensions['sqlalchemy'].db.engine
        with engine.connect() as connection:
            return connection.execute(
                sqlalchemy.text(
                    'SELECT password, status_id, reset_password_token '
                    'FROM "user" WHERE id = :id'
                ),
                {'id': user_id},
            ).first()


def _register(app, email, token):
    register = AuthenticationResource.register_user.view_func
    with app.test_request_context('/api2/authentication/register', method='POST'):
        return register(
            None,
            email=email,
            firstname='First',
            lastname='Last',
            password=NEW_PASSWORD,
            invite_token=token,
        )


def _cookie(response):
    return response.headers['Set-Cookie'].split(';', 1)[0].split('=', 1)[1]


def test_an_empty_invitation_token_registers_nobody(app):
    """Account 1 is the first of the accounts whose token is the default."""
    before = _row(app, 1)

    with pytest.raises(BadRequest):
        _register(app, 'john.doe@moh.gov.rw', '')

    assert _row(app, 1) == before


def test_an_empty_invitation_token_does_not_register_a_pending_account_holding_none(
    app,
):
    """A pending account whose token was cleared (or never set) holds the
    empty string, so only the empty-token guard stops this."""
    _run(app, 'UPDATE "user" SET reset_password_token = \'\' WHERE id = 4')
    before = _row(app, 4)

    with pytest.raises(BadRequest):
        _register(app, 'Pending.User@moh.gov.rw', '')

    assert _row(app, 4) == before


@pytest.mark.parametrize('status', [UserStatusEnum.ACTIVE, UserStatusEnum.INACTIVE])
def test_a_reset_token_does_not_register_an_account_that_is_not_pending(app, status):
    _run(
        app,
        'UPDATE "user" SET status_id = :status, reset_password_token = :token '
        'WHERE id = 8',
        status=status.value,
        token='forgot-password-token-8',
    )
    before = _row(app, 8)

    with pytest.raises(BadRequest):
        _register(app, JANE, 'forgot-password-token-8')

    assert _row(app, 8) == before


def test_an_invitation_registers_once(app):
    response = _register(app, 'Pending.User@moh.gov.rw', 'invite-4')

    assert signed_in_id(app, _cookie(response)) == 4
    after = _row(app, 4)
    assert after.status_id == UserStatusEnum.ACTIVE.value
    assert after.reset_password_token == ''

    with pytest.raises(BadRequest):
        _register(app, 'Pending.User@moh.gov.rw', 'invite-4')


def test_of_two_pending_twins_only_the_first_registers(app):
    _run(
        app,
        'UPDATE "user" SET status_id = :status, reset_password_token = :token '
        'WHERE id = 10',
        status=UserStatusEnum.PENDING.value,
        token='invite-10',
    )

    _register(app, 'dup.shell@moh.gov.rw', 'invite-11')
    with pytest.raises(BadRequest):
        _register(app, 'Dup.Shell@moh.gov.rw', 'invite-10')

    assert _row(app, 11).status_id == UserStatusEnum.ACTIVE.value
    assert _row(app, 10).status_id == UserStatusEnum.PENDING.value
