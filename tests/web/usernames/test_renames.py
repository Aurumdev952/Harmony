"""WP-0k: renames cannot reach another account's sign-in.

Two paths rename an account: an admin's `PATCH /api2/user/<id>` and the
change-username page flask-user serves to every signed-in user. Before WP-0k a
rename could pick a username that pattern-matched another account's
(`j_hn.doe` matches `john.doe` under ILIKE), and sign-in then resolved it to
that account. Now sign-in matches exactly, and a rename to a username equal to
another account's ignoring case is refused, since it would leave both
accounts' other spellings matching nobody.
"""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import sqlalchemy
from werkzeug.exceptions import BadRequest

from models.alchemy.user import User
from tests.web.usernames.accounts import PASSWORD
from tests.web.usernames.tokens import (
    login,
    session_token_without_account_id,
    signed_in_id,
)

ANN = 'ann@moh.gov.rw'  # account 6
LOOK_ALIKE = 'j_hn.doe@moh.gov.rw'  # pattern-matches account 1, john.doe


def _username(app, user_id):
    with app.app_context():
        engine = app.extensions['sqlalchemy'].db.engine
        with engine.connect() as connection:
            return connection.execute(
                sqlalchemy.text('SELECT username FROM "user" WHERE id = :id'),
                {'id': user_id},
            ).scalar()


def _change_username_page(app, username, new_username):
    client = app.test_client()
    token = login(app, username)
    return client.post(
        '/user/change-username',
        data={'new_username': new_username, 'old_password': PASSWORD},
        headers={'Authorization': f'Bearer {token}'},
    )


@pytest.mark.parametrize(
    'new_username',
    [
        'JOHN.DOE@moh.gov.rw',
        'Mixed.Case@moh.gov.rw',
        'ANN@moh.gov.rw',
        'DUP.SHELL@moh.gov.rw',
    ],
)
def test_change_username_page_refuses_another_accounts_name_in_any_case(
    app, new_username
):
    response = _change_username_page(app, 'jane.doe@moh.gov.rw', new_username)

    assert response.status_code == 200  # the form again, with the error
    assert b'already in use' in response.data
    assert _username(app, 8) == 'jane.doe@moh.gov.rw'


def test_change_username_page_allows_a_new_case_of_ones_own_name(app):
    response = _change_username_page(app, 'jane.doe@moh.gov.rw', 'Jane.Doe@moh.gov.rw')

    assert response.status_code == 302
    assert _username(app, 8) == 'Jane.Doe@moh.gov.rw'


def test_a_look_alike_rename_signs_in_only_the_renamed_account(app):
    response = _change_username_page(app, ANN, LOOK_ALIKE)
    assert response.status_code == 302
    assert _username(app, 6) == LOOK_ALIKE

    assert signed_in_id(app, login(app, LOOK_ALIKE)) == 6
    # A session minted before WP-0k names only the username it was typed with.
    assert signed_in_id(app, session_token_without_account_id(app, LOOK_ALIKE)) == 6
    assert signed_in_id(app, login(app, 'john.doe@moh.gov.rw')) == 1


@pytest.fixture(name='user_api')
def fixture_user_api(app, monkeypatch):
    with app.app_context():
        # pylint: disable=import-outside-toplevel
        from web.server.api import user_api_models
    # The caller holds edit_user; the check under test runs before any update.
    monkeypatch.setattr(
        user_api_models, 'AuthorizedOperation', lambda *args: nullcontext()
    )
    return user_api_models


@pytest.mark.parametrize(
    'new_username', ['JOHN.DOE@moh.gov.rw', 'ANN@moh.gov.rw', 'mixed.case@moh.gov.rw']
)
def test_user_patch_refuses_another_accounts_name_in_any_case(
    app, request_ctx, user_api, new_username
):
    with app.app_context():
        db_user = app.user_manager.find_user_by_username('jane.doe@moh.gov.rw')
        update_user = user_api.UserResource.update_user.view_func

        with pytest.raises(BadRequest):
            update_user(None, db_user, {'username': new_username})

    assert _username(app, 8) == 'jane.doe@moh.gov.rw'


def test_a_look_alike_rename_by_patch_signs_in_only_the_renamed_account(
    app, request_ctx, user_api, monkeypatch
):
    """`PATCH /api2/user/<id>` writes the username through Potion's manager;
    the steps around it need tables this app does not have. WP-0j's steps are
    stubbed too, so the test also runs on the WP-0j merge."""
    for step in (
        'update_user_acls',
        'update_user_groups',
        'update_user_api_tokens',
        'invalidate_user_identity_cache',
        'verify_may_rename',
        'held_roles_from_uris',
        'member_groups_from_uris',
        'verify_acl_grants',
        'replace_user_acls',
    ):
        monkeypatch.setattr(user_api, step, lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(
        user_api,
        'build_user_updates',
        lambda obj, *_roles: {'username': obj['username']},
    )

    def update(user, updates):
        for name, value in updates.items():
            setattr(user, name, value)
        app.extensions['sqlalchemy'].db.session.commit()
        return user

    manager = SimpleNamespace(update=update, can_update_item=lambda user: True)
    with app.app_context():
        db_user = User.query.get(6)
        user_api.UserResource.update_user.view_func(
            SimpleNamespace(manager=manager),
            db_user,
            {'username': LOOK_ALIKE, 'roles': []},
        )

    assert _username(app, 6) == LOOK_ALIKE
    assert signed_in_id(app, login(app, LOOK_ALIKE)) == 6
    assert signed_in_id(app, session_token_without_account_id(app, LOOK_ALIKE)) == 6
    assert signed_in_id(app, login(app, 'john.doe@moh.gov.rw')) == 1
