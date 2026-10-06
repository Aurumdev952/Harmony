'''WP-0k: a reset or invitation token sets a password once.

`reset_password` checked only the token's signature and age (two days), so an
invitation already spent on registration, an older reset link after a newer
one, or the same link twice all set the password again. A token now works only
while it is the account's stored `reset_password_token`, and is cleared when
used.
'''

import pytest
import sqlalchemy
from werkzeug.exceptions import BadRequest

from tests.web.usernames.tokens import (
    complete_reset,
    login,
    mailed_reset_token,
    signed_in_id,
)
from models.alchemy.user import UserStatusEnum
from tests.web.usernames.accounts import PASSWORD
from web.server.api import authentication_api_models as auth_models
from web.server.api.authentication_api_models import AuthenticationResource
from web.server.util.api_validation import GenericValidationError

PENDING = 4  # Pending.User@moh.gov.rw
JANE = 8  # jane.doe@moh.gov.rw
FIRST = 'a first new password 1A!'
SECOND = 'a second new password 2B!'


def _store_token(app, user_id, token):
    with app.app_context():
        engine = app.extensions['sqlalchemy'].db.engine
        with engine.begin() as connection:
            connection.execute(
                sqlalchemy.text(
                    'UPDATE "user" SET reset_password_token = :token WHERE id = :id'
                ),
                {'token': token, 'id': user_id},
            )


def _refused(app, token, password):
    with pytest.raises(GenericValidationError) as raised:
        complete_reset(app, token, password)
    return [(error.validator, error.message) for error in raised.value.errors]


def test_a_reset_link_sets_the_password_once(app):
    token = mailed_reset_token(app, JANE)

    assert complete_reset(app, token, FIRST).status_code == 200
    _refused(app, token, SECOND)

    assert signed_in_id(app, login(app, 'jane.doe@moh.gov.rw', FIRST)) == JANE


def test_an_older_reset_link_is_refused_after_a_newer_one_is_mailed(app):
    older = mailed_reset_token(app, JANE)
    # A later mail stores its own token (tokens minted in the same second are
    # equal, so the newer one is written directly).
    _store_token(app, JANE, 'a-newer-reset-token')

    _refused(app, older, FIRST)


def test_an_invitation_spent_on_registration_is_not_a_reset_link(app):
    token = mailed_reset_token(app, PENDING)
    register = AuthenticationResource.register_user.view_func
    with app.test_request_context('/api2/authentication/register', method='POST'):
        register(
            None,
            email='Pending.User@moh.gov.rw',
            firstname='Pending',
            lastname='User',
            password=FIRST,
            invite_token=token,
        )

    _refused(app, token, SECOND)

    assert signed_in_id(app, login(app, 'Pending.User@moh.gov.rw', FIRST)) == PENDING


def test_an_invitation_used_at_reset_is_spent_for_registration(app):
    """R-4: an invitee may set its first password from its invitation at reset,
    once; registering with it afterwards is refused."""
    token = mailed_reset_token(app, PENDING)

    assert complete_reset(app, token, FIRST).status_code == 200

    register = AuthenticationResource.register_user.view_func
    with app.test_request_context('/api2/authentication/register', method='POST'):
        with pytest.raises(BadRequest):
            register(
                None,
                email='Pending.User@moh.gov.rw',
                firstname='Pending',
                lastname='User',
                password=SECOND,
                invite_token=token,
            )
    assert signed_in_id(app, login(app, 'Pending.User@moh.gov.rw', FIRST)) == PENDING


def test_a_valid_token_is_refused_when_the_account_holds_none(app):
    token = mailed_reset_token(app, JANE)
    _store_token(app, JANE, '')

    _refused(app, token, FIRST)


def test_a_spent_token_gets_the_same_answer_as_a_forged_one(app):
    token = mailed_reset_token(app, JANE)
    complete_reset(app, token, FIRST)

    assert _refused(app, token, SECOND) == _refused(app, 'forged.token', SECOND)


def test_of_two_concurrent_resets_with_one_token_only_one_writes(app, monkeypatch):
    """The other request spends the token between this one's checks and its
    write; the write is conditional on the token, so it writes nothing."""
    token = mailed_reset_token(app, JANE)
    may_set = auth_models.may_set_password_from_reset

    def spent_meanwhile(user):
        _store_token(app, JANE, '')
        return may_set(user)

    monkeypatch.setattr(auth_models, 'may_set_password_from_reset', spent_meanwhile)

    _refused(app, token, FIRST)
    assert signed_in_id(app, login(app, 'jane.doe@moh.gov.rw', PASSWORD)) == JANE


def test_of_two_concurrent_registrations_with_one_invitation_only_one_writes(
    app, monkeypatch
):
    token = mailed_reset_token(app, PENDING)
    taken = auth_models.username_taken

    def spent_meanwhile(*args, **kwargs):
        _store_token(app, PENDING, '')
        return taken(*args, **kwargs)

    monkeypatch.setattr(auth_models, 'username_taken', spent_meanwhile)

    register = AuthenticationResource.register_user.view_func
    with app.test_request_context('/api2/authentication/register', method='POST'):
        with pytest.raises(BadRequest):
            register(
                None,
                email='Pending.User@moh.gov.rw',
                firstname='Pending',
                lastname='User',
                password=FIRST,
                invite_token=token,
            )
    with app.app_context():
        engine = app.extensions['sqlalchemy'].db.engine
        with engine.connect() as connection:
            status = connection.execute(
                sqlalchemy.text('SELECT status_id FROM "user" WHERE id = 4')
            ).scalar()
    assert status == UserStatusEnum.PENDING.value
