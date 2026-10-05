"""WP-0k: a token signs in only the account it was issued to.

Browser sessions last up to 365 days and API tokens up to 20 years, and both
named their account only by username. Once an account was deleted (or renamed)
and another took its username, the old token signed in the new account. A
session now carries the account id, and an API token is tied to its row's
`user_id`, even while the app's cache still remembers the deleted token.
A session minted before WP-0k carries no id, so it signs in only an account
created no later than the second it was issued.
"""

from datetime import datetime, timedelta, timezone

import sqlalchemy
from flask_jwt_extended import decode_token

from tests.web.usernames.tokens import (
    api_token,
    login,
    session_token_without_account_id,
    signed_in_id,
)

JOHN_DOE = 'john_doe@moh.gov.rw'  # account 2 in accounts.py
JOHN_DOT_DOE = 'john.doe@moh.gov.rw'  # account 1
TOKEN_ID = 'tok0000002'


def _run(app, sql, **params):
    with app.app_context():
        engine = app.extensions['sqlalchemy'].db.engine
        with engine.begin() as connection:
            connection.execute(sqlalchemy.text(sql), params)


def _delete_and_recreate(app, username, old_id, new_id, created=None):
    _run(app, 'DELETE FROM api_token WHERE user_id = :id', id=old_id)
    _run(app, 'DELETE FROM "user" WHERE id = :id', id=old_id)
    _run(
        app,
        'INSERT INTO "user" (id, username, password, reset_password_token, '
        "first_name, last_name, phone_number, status_id, created) "
        "VALUES (:id, :username, '', '', 'New', 'Owner', '', 1, :created)",
        id=new_id,
        username=username,
        # As the database writes it: UTC, with microseconds.
        created=created or datetime.now(timezone.utc).replace(tzinfo=None),
    )


def _set_created(app, user_id, created):
    _run(
        app,
        'UPDATE "user" SET created = :created WHERE id = :id',
        id=user_id,
        created=created,
    )


def _issued_at(app, token):
    with app.app_context():
        issued_at = decode_token(token)['iat']
    return datetime.fromtimestamp(issued_at, timezone.utc).replace(tzinfo=None)


def _rename(app, user_id, username):
    _run(
        app,
        'UPDATE "user" SET username = :username WHERE id = :id',
        id=user_id,
        username=username,
    )


def test_session_does_not_sign_in_an_account_that_reuses_the_username(app):
    token = login(app, JOHN_DOE)
    assert signed_in_id(app, token) == 2

    _delete_and_recreate(app, JOHN_DOE, old_id=2, new_id=12)

    assert signed_in_id(app, token) is None


def test_api_token_does_not_sign_in_an_account_that_reuses_the_username(app):
    _run(
        app,
        'INSERT INTO api_token (id, user_id, is_revoked) VALUES (:id, 2, 0)',
        id=TOKEN_ID,
    )
    token = api_token(app, JOHN_DOE, TOKEN_ID)
    # Signing in once leaves the token's owner in the app's cache.
    assert signed_in_id(app, token) == 2

    _delete_and_recreate(app, JOHN_DOE, old_id=2, new_id=12)

    assert signed_in_id(app, token) is None


def test_revoked_api_token_signs_in_nobody(app):
    _run(
        app,
        'INSERT INTO api_token (id, user_id, is_revoked) VALUES (:id, 2, 1)',
        id=TOKEN_ID,
    )
    assert signed_in_id(app, api_token(app, JOHN_DOE, TOKEN_ID)) is None


def test_session_does_not_follow_its_username_to_a_renamed_account(app):
    token = login(app, JOHN_DOT_DOE)
    _rename(app, 1, 'john.doe.old@moh.gov.rw')
    assert signed_in_id(app, token) is None

    # Another account renamed to the old username.
    _rename(app, 3, JOHN_DOT_DOE)
    assert signed_in_id(app, token) is None


def test_session_issued_after_a_rename_signs_in_the_renamed_account(app):
    _rename(app, 1, 'john.renamed@moh.gov.rw')

    assert signed_in_id(app, login(app, 'john.renamed@moh.gov.rw')) == 1


def test_session_minted_before_wp0k_does_not_sign_in_a_recreated_account(app):
    token = session_token_without_account_id(app, JOHN_DOT_DOE)
    assert signed_in_id(app, token) == 1

    # In the next second at the earliest: `iat` has whole seconds.
    _delete_and_recreate(
        app,
        JOHN_DOT_DOE,
        old_id=1,
        new_id=12,
        created=_issued_at(app, token) + timedelta(seconds=1),
    )

    assert signed_in_id(app, token) is None


def test_session_minted_before_wp0k_signs_in_its_account(app):
    """Issued in the same second the account was created: `iat` has whole
    seconds and `created` has microseconds."""
    token = session_token_without_account_id(app, JOHN_DOT_DOE)
    _set_created(app, 1, _issued_at(app, token).replace(microsecond=999999))

    assert signed_in_id(app, token) == 1


def test_session_minted_before_wp0k_signs_in_an_account_with_no_created_time(app):
    """Accounts older than the `created` column have none to compare."""
    token = session_token_without_account_id(app, JOHN_DOT_DOE)
    _set_created(app, 1, None)

    assert signed_in_id(app, token) == 1


def test_session_minted_before_wp0k_is_refused_by_an_account_created_after_it(app):
    token = session_token_without_account_id(app, JOHN_DOT_DOE)
    _set_created(app, 1, _issued_at(app, token) + timedelta(seconds=1))

    assert signed_in_id(app, token) is None


def test_session_minted_before_wp0k_follows_its_username_to_a_renamed_account(app):
    """The residual: an account created before the session and renamed to its
    username after it. `user` records no rename time (WP-0k file, INV-3)."""
    token = session_token_without_account_id(app, JOHN_DOT_DOE)
    _rename(app, 1, 'john.doe.old@moh.gov.rw')
    _rename(app, 3, JOHN_DOT_DOE)

    assert signed_in_id(app, token) == 3
