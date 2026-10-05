"""WP-0k: a request about one account acts on that account.

Usernames are unique only as stored, so an account can have a case-only twin
(`Dup.Shell@` active and `dup.shell@` pending, accounts 10 and 11). A route
that already holds the account it authorised must not look it up again by
username, and nothing may add an account equal to another ignoring case.
"""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import sqlalchemy
from flask_potion.signals import before_create
from werkzeug.exceptions import BadRequest

from models.alchemy.user import User, UserStatusEnum
from tests.web.usernames.accounts import PASSWORD
from tests.web.usernames.tokens import session_token_without_account_id, signed_in_id
from web.server.api.authentication_api_models import AuthenticationResource
from web.server.data.data_access import Transaction

PENDING_TWIN = 'dup.shell@moh.gov.rw'  # account 11, invitation token invite-11


def _column(app, user_id, column):
    with app.app_context():
        engine = app.extensions['sqlalchemy'].db.engine
        with engine.connect() as connection:
            return connection.execute(
                # The column names are this file's own.
                sqlalchemy.text(f'SELECT {column} FROM "user" WHERE id = :id'),  # noqa: S608
                {'id': user_id},
            ).scalar()


@pytest.fixture(name='user_api')
def fixture_user_api(app):
    with app.app_context():
        # pylint: disable=import-outside-toplevel
        from web.server.api import user_api_models
    return user_api_models


@pytest.fixture(name='mailed_to')
def fixture_mailed_to(app, monkeypatch, user_api):
    """The ids of the accounts a reset mail goes to."""
    # pylint: disable=import-outside-toplevel
    from web.server.routes.views import admin

    monkeypatch.setattr(user_api, 'AuthorizedOperation', lambda *args: nullcontext())
    # WP-0j's guard, once merged: the caller is a superuser here.
    monkeypatch.setattr(
        user_api, 'verify_may_reset_password', lambda *args: None, raising=False
    )
    monkeypatch.setattr(
        admin, 'deployment_url', lambda *args, **kwargs: 'https://harmony.invalid/r'
    )
    sent = []
    renderer = SimpleNamespace(
        create_password_reset_message=lambda _sender, user, _link: user.id
    )
    monkeypatch.setattr(app, 'email_renderer', renderer, raising=False)
    monkeypatch.setattr(
        app,
        'notification_service',
        SimpleNamespace(send_email=sent.append),
        raising=False,
    )
    return sent


def test_admin_reset_of_a_pending_twin_resets_that_account(
    app, request_ctx, user_api, mailed_to
):
    user_api.UserResource.reset_password.view_func(None, User.query.get(11))

    assert mailed_to == [11]
    assert _column(app, 11, 'reset_password_token') not in ('', 'invite-11')
    assert _column(app, 10, 'reset_password_token') == ''


def test_registering_a_pending_twin_of_an_active_account_is_refused(app):
    token = session_token_without_account_id(app, PENDING_TWIN)
    assert signed_in_id(app, token) == 10

    register = AuthenticationResource.register_user.view_func
    with app.test_request_context('/api2/authentication/register', method='POST'):
        with pytest.raises(BadRequest):
            register(
                None,
                email=PENDING_TWIN,
                firstname='Dup',
                lastname='Shell',
                password=PASSWORD,
                invite_token='invite-11',
            )

    assert _column(app, 11, 'status_id') == UserStatusEnum.PENDING.value
    assert signed_in_id(app, token) == 10


@pytest.mark.parametrize(
    'username, refused',
    [
        ('JOHN.DOE@moh.gov.rw', True),
        ('ann@MOH.GOV.RW', True),
        ('j_hn.doe@moh.gov.rw', False),
        ('brand.new@moh.gov.rw', False),
    ],
)
def test_potion_user_create_refuses_a_username_taken_ignoring_case(
    app, request_ctx, user_api, username, refused
):
    with app.app_context():
        item = User(username=username, first_name='New', last_name='User')
        # The receiver itself: other suites connect their own to this signal.
        assert user_api.before_create_user in before_create.receivers_for(
            user_api.UserResource
        )
        if refused:
            with pytest.raises(BadRequest):
                user_api.before_create_user(user_api.UserResource, item)
        else:
            user_api.before_create_user(user_api.UserResource, item)


@pytest.fixture(name='create_user')
def fixture_create_user(app):
    # pylint: disable=import-outside-toplevel
    from scripts.create_user import create_user

    def run(username, overwrite):
        with app.app_context():
            session = app.extensions['sqlalchemy'].db.session
            with Transaction(
                should_commit=None, get_session=lambda: session
            ) as transaction:
                create_user(
                    transaction,
                    username,
                    'Script',
                    'User',
                    PASSWORD,
                    overwrite_user=overwrite,
                )
            session.commit()

    return run


# scripts/create_user.py belongs to the lead. The change is requested in the
# WP-0k file (WP-0k-evidence/requests/create_user.md). Strict, so these fail
# once it lands, and the marks go with it.
PENDING_SCRIPT_CHANGE = pytest.mark.xfail(
    strict=True, reason='scripts/create_user.py still looks usernames up with ILIKE'
)


@PENDING_SCRIPT_CHANGE
def test_create_user_script_overwrites_only_the_exact_account(app, create_user):
    create_user('john_doe@moh.gov.rw', overwrite=True)

    assert _column(app, 1, 'first_name') == 'First'
    assert _column(app, 2, 'first_name') == 'Script'


@pytest.mark.parametrize(
    'overwrite', [pytest.param(True, marks=PENDING_SCRIPT_CHANGE), False]
)
def test_create_user_script_refuses_a_username_two_accounts_equal(
    app, create_user, overwrite
):
    with pytest.raises(ValueError):
        create_user('ANN@moh.gov.rw', overwrite=overwrite)

    with app.app_context():
        assert User.query.filter(User.username == 'ANN@moh.gov.rw').count() == 0
