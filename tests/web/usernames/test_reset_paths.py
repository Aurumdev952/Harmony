'''WP-0k: one rule for setting a password from a reset link.

Two views take a reset token: Harmony's `POST /api2/authentication/reset_password`
and flask-user's `/user/reset-password/<token>`, which production registers
(`USER_ENABLE_FORGOT_PASSWORD`). flask-user's view now only sends the browser
to Harmony's reset page, so the API's rule is the only one: an active account,
or a pending one with no registered case twin, which it activates. The public
forgot-password form mails only active accounts.
'''

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import sqlalchemy

from models.alchemy.user import UserStatusEnum
from tests.web.usernames.tokens import mailed_reset_token
from web.server.api.authentication_api_models import AuthenticationResource

NEW_PASSWORD = 'a new password 2B!'


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


def _set_status(app, user_id, status):
    with app.app_context():
        engine = app.extensions['sqlalchemy'].db.engine
        with engine.begin() as connection:
            connection.execute(
                sqlalchemy.text('UPDATE "user" SET status_id = :status WHERE id = :id'),
                {'status': status.value, 'id': user_id},
            )


def _token(app, user_id):
    return mailed_reset_token(app, user_id)


@pytest.mark.parametrize(
    'user_id, status',
    [
        (8, UserStatusEnum.ACTIVE),
        (8, UserStatusEnum.INACTIVE),
        (4, UserStatusEnum.PENDING),
        (11, UserStatusEnum.PENDING),
    ],
)
@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_flask_user_reset_view_only_sends_the_browser_to_harmonys_page(
    app, user_id, status, method
):
    _set_status(app, user_id, status)
    token = _token(app, user_id)
    before = _row(app, user_id)

    response = app.test_client().open(
        f'/user/reset-password/{token}',
        method=method,
        data={'new_password': NEW_PASSWORD, 'retype_password': NEW_PASSWORD},
    )

    assert response.status_code == 302
    location = urlsplit(response.headers['Location'])
    origin = urlsplit(app.zen_config.general.DEPLOYMENT_BASE_URL)
    assert (location.scheme, location.netloc, location.path) == (
        'https',
        origin.netloc,
        '/user/reset-password',
    )
    assert parse_qs(location.query) == {'token': [token]}
    assert _row(app, user_id) == before


@pytest.fixture(name='mailed_to')
def fixture_mailed_to(app, monkeypatch):
    # pylint: disable=import-outside-toplevel
    from web.server.routes.views import admin

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


def _forgot(app, email):
    forgot = AuthenticationResource.forgot_password.view_func
    with app.test_request_context(
        '/api2/authentication/forgot_password', method='POST'
    ):
        return forgot(None, email=email)


@pytest.mark.parametrize(
    'email, user_id, status',
    [
        ('Pending.User@moh.gov.rw', 4, UserStatusEnum.PENDING),
        ('jane.doe@moh.gov.rw', 8, UserStatusEnum.INACTIVE),
    ],
)
def test_forgot_password_treats_an_account_that_cannot_sign_in_as_unknown(
    app, request_ctx, mailed_to, email, user_id, status
):
    '''A pending invitee completes its invitation instead; its invitation
    token stays as it was.'''
    _set_status(app, user_id, status)
    before = _row(app, user_id)

    assert _forgot(app, email) == _forgot(app, 'nobody@moh.gov.rw')
    assert mailed_to == []
    assert _row(app, user_id) == before


def test_forgot_password_mails_an_active_account(app, request_ctx, mailed_to):
    assert _forgot(app, 'jane.doe@moh.gov.rw')[1] == 200
    assert mailed_to == [8]


def test_the_api_reset_activates_a_pending_account_and_keeps_its_names(app):
    """Registering also sets the status and the password, and nothing else
    that is stored (its `firstname` and `lastname` attributes are not columns)."""
    before = _row(app, 4)
    reset = AuthenticationResource.reset_password.view_func
    with app.test_request_context('/api2/authentication/reset_password', method='POST'):
        reset(None, token=_token(app, 4), password=NEW_PASSWORD)

    after = _row(app, 4)
    assert after.status_id == UserStatusEnum.ACTIVE.value
    assert after.password != before.password


@pytest.mark.parametrize(
    'path', ['/user/confirm-email/any-token', '/user/resend-confirm-email']
)
def test_flask_user_confirm_views_are_not_registered(app, path):
    '''Production turns off `USER_ENABLE_CONFIRM_EMAIL`, so no other flask-user
    view turns a token into an account.'''
    assert app.test_client().get(path).status_code == 404
