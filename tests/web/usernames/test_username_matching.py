"""WP-0k: usernames match exactly, ignoring case, never as a LIKE pattern.

Before WP-0k, JWT login and flask-user resolved a username with `ILIKE` and
`first()`, so `_` and `%` were wildcards, and the JWT identity was the string
the user typed. A look-alike account (`jane_doe` for `jane.doe`) that
registered through an invitation was signed in as the older account, with its
roles and query policy.
"""

import json

import pytest
from flask import current_app
from flask_jwt_extended import decode_token
from flask_login import current_user

from models.alchemy.user import User
from tests.web.usernames.accounts import ACCOUNTS, PASSWORD
from web.server.api.authentication_api_models import AuthenticationResource
from web.server.errors import UserAlreadyInvited
from web.server.routes.views import users
from web.server.util.authentication import create_user_access_token

# (what the caller sends, the id it must resolve to; None means nobody)
LOOKUPS = [
    ('john.doe@moh.gov.rw', 1),
    ('john_doe@moh.gov.rw', 2),
    ('JOHN.DOE@MOH.GOV.RW', 1),
    ('John_Doe@moh.gov.rw', 2),
    ('mixed.case@moh.gov.rw', 3),
    ('Mixed.Case@moh.gov.rw', 3),
    ('ann@moh.gov.rw', 6),
    ('Ann@moh.gov.rw', 5),
    # Two accounts equal this ignoring case and neither exactly.
    ('ANN@moh.gov.rw', None),
    ('percent%sign@moh.gov.rw', 7),
    ('PERCENT%SIGN@moh.gov.rw', 7),
    ('j_hn.doe@moh.gov.rw', None),
    ('john%@moh.gov.rw', None),
    ('%', None),
    ('_%', None),
    ('jane_doe@moh.gov.rw', 9),
]
CASES = pytest.mark.parametrize(
    'sent, expected_id', LOOKUPS, ids=[c[0] for c in LOOKUPS]
)


def _signed_in_id(app, identity):
    with app.test_request_context('/'):
        token = create_user_access_token(identity)
    with app.test_request_context('/', headers={'Authorization': f'Bearer {token}'}):
        return current_user.id if current_user.is_authenticated else None


@CASES
def test_jwt_identity_signs_in_the_matching_account(app, sent, expected_id):
    assert _signed_in_id(app, sent) == expected_id


@CASES
def test_flask_user_lookup_matches_exactly(app, request_ctx, sent, expected_id):
    user = current_app.user_manager.find_user_by_username(sent)
    assert (user.id if user else None) == expected_id


@CASES
def test_role_assignment_lookup_matches_exactly(app, request_ctx, sent, expected_id):
    user = users.try_get_user(sent)
    assert (user.id if user else None) == expected_id


def _login(app, email):
    login = AuthenticationResource.login_user_route.view_func
    with app.test_request_context('/api2/authentication/login?set_cookie=false'):
        response = login(None, email=email, password=PASSWORD, remember_me=False)
        return decode_token(json.loads(response.get_data())['access_token'])


@pytest.mark.parametrize(
    'typed, username',
    [
        ('john_doe@moh.gov.rw', 'john_doe@moh.gov.rw'),
        ('JOHN.DOE@moh.gov.rw', 'john.doe@moh.gov.rw'),
        ('mixed.case@moh.gov.rw', 'Mixed.Case@moh.gov.rw'),
    ],
)
def test_login_token_names_the_stored_username(app, typed, username):
    claims = _login(app, typed)

    assert claims['identity'] == username
    expected_id = next(i for i, name, *_ in ACCOUNTS if name == username)
    assert _signed_in_id(app, claims['identity']) == expected_id


def test_registering_a_look_alike_signs_in_the_new_account(app):
    register = AuthenticationResource.register_user.view_func
    with app.test_request_context('/api2/authentication/register', method='POST'):
        response = register(
            None,
            email='jane_doe@moh.gov.rw',
            firstname='Jane',
            lastname='Look-alike',
            password=PASSWORD,
            invite_token='invite-9',
        )
        cookie = response.headers['Set-Cookie'].split(';', 1)[0]

    with app.test_request_context('/', headers={'Cookie': cookie}):
        assert current_user.id == 9


@pytest.mark.parametrize(
    'email, existing',
    [('mixed.case@moh.gov.rw', 'Mixed.Case@moh.gov.rw'), ('ANN@moh.gov.rw', None)],
)
def test_inviting_an_existing_account_in_another_case_is_refused(
    app, request_ctx, monkeypatch, email, existing
):
    monkeypatch.setattr(users, 'send_invite_emails', lambda pending: None)

    with pytest.raises(UserAlreadyInvited):
        users.invite_users([users.Invitee(name='Someone', email=email)])

    assert _usernames_like(email) == {
        name for _, name, *_ in ACCOUNTS if name.lower() == email.lower()
    }
    assert existing is None or existing in _usernames_like(email)


def test_reinviting_a_pending_account_in_another_case_reuses_it(
    app, request_ctx, monkeypatch
):
    sent = []
    monkeypatch.setattr(users, 'send_invite_emails', sent.extend)

    invited = users.invite_users(
        [users.Invitee(name='Pending', email='pending.user@moh.gov.rw')]
    )

    assert [user.id for user in invited] == [4]
    assert [user.id for user in sent] == [4]
    assert _usernames_like('pending.user@moh.gov.rw') == {'Pending.User@moh.gov.rw'}


def _usernames_like(email):
    rows = User.query.all()  # pylint: disable=no-member
    return {row.username for row in rows if row.username.lower() == email.lower()}
