"""WP-0k: every link the server mails is on the configured DEPLOYMENT_BASE_URL.

Before WP-0k, the reset, invite, access-granted and new-dashboard links came
from `url_for(..., _external=True)`, which reads the request's Host header and
`SCRIPT_NAME`. A forged Host on the anonymous `forgot_password` route mailed a
working reset token to the attacker's host.
"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from models.alchemy.dashboard import Dashboard
from models.alchemy.permission import ResourceTypeEnum
from models.alchemy.user import User
from tests.web.links.support import (
    HOSTILE_ENVIRONS,
    INVITER,
    ORIGIN,
    FakeUser,
    mailed_links,
    request_as,
)
from web.server.routes.views import admin, invite

ENVIRONS = pytest.mark.parametrize(
    'environ', list(HOSTILE_ENVIRONS.values()), ids=list(HOSTILE_ENVIRONS)
)

TARGET = FakeUser(7, 'target@harmony.example.org')
PENDING = FakeUser(9, 'pending@harmony.example.org')
DASHBOARD_RESOURCE = SimpleNamespace(
    id=5,
    # Resource names are the slug with `-` replaced by `_`.
    name='malaria_overview',
    label='Malaria overview',
    resource_type=SimpleNamespace(name=ResourceTypeEnum.DASHBOARD),
)
DASHBOARD = SimpleNamespace(slug='malaria-overview', resource_id=DASHBOARD_RESOURCE.id)


def fake_transaction(rows):
    """A `Transaction` whose `find_one_by_fields` answers from `rows`, a list of
    (entity class, search fields, result)."""

    class FakeTransaction:
        def find_one_by_fields(self, entity, case_sensitive, search_fields):
            assert case_sensitive
            for row_entity, row_fields, result in rows:
                if row_entity is entity and row_fields == search_fields:
                    return result
            return None

        @staticmethod
        def add_or_update(item, flush=False):
            return item

    @contextmanager
    def transaction():
        yield FakeTransaction()

    return transaction


@pytest.fixture(name='permission_models')
def fixture_permission_models(app):
    # Its imports need an application context.
    with app.app_context():
        # pylint: disable=import-outside-toplevel
        from web.server.api import permission_api_models
    return permission_api_models


@pytest.fixture(name='dashboard_models')
def fixture_dashboard_models(app):
    with app.app_context():
        # pylint: disable=import-outside-toplevel
        from web.server.api import dashboard_api_models
    return dashboard_api_models


def _send_reset(app, monkeypatch, environ):
    monkeypatch.setattr(
        admin,
        'Transaction',
        fake_transaction([(User, {'username': TARGET.username}, TARGET)]),
    )
    with request_as(app, environ, path='/api2/authentication/forgot_password'):
        admin.send_reset_password(TARGET.username)


@ENVIRONS
def test_reset_link_is_on_the_configured_origin(app, mailer, monkeypatch, environ):
    _send_reset(app, monkeypatch, environ)

    [message] = mailer.messages
    assert mailed_links(message, 'token=') == {
        f'{ORIGIN}/user/reset-password?token=token-7'
    }


@ENVIRONS
def test_invite_link_is_on_the_configured_origin(app, mailer, environ):
    with request_as(app, environ, username=INVITER.username):
        invite.send_invite_emails([PENDING])

    [message] = mailer.messages
    assert mailed_links(message, 'token=') == {f'{ORIGIN}/zen/register?token=token-9'}


@ENVIRONS
def test_access_granted_link_is_the_dashboard_page_on_the_configured_origin(
    app, mailer, monkeypatch, permission_models, environ
):
    monkeypatch.setattr(
        permission_models,
        'Transaction',
        fake_transaction(
            [(Dashboard, {'resource_id': DASHBOARD_RESOURCE.id}, DASHBOARD)]
        ),
    )
    with request_as(app, environ, username=INVITER.username):
        permission_models.send_email(
            DASHBOARD_RESOURCE,
            existing_roles={'userRoles': {}},
            new_roles={
                'userRoles': {'viewer@harmony.example.org': ['dashboard_viewer']}
            },
        )

    [message] = mailer.messages
    # The dashboard's slug, not the resource name: `malaria_overview` is no
    # longer a wildcard for `malaria-overview` since WP-0i.
    assert mailed_links(message, '/dashboard/') == {
        f'{ORIGIN}/dashboard/malaria-overview?source=dashboard_permission_email'
    }


@ENVIRONS
def test_new_dashboard_link_is_on_the_configured_origin(
    app, mailer, dashboard_models, environ
):
    item = SimpleNamespace(
        author=INVITER,
        author_username=INVITER.username,
        slug=DASHBOARD.slug,
        resource=DASHBOARD_RESOURCE,
    )
    with request_as(app, environ, username=INVITER.username):
        dashboard_models.send_email_after_create(None, item)

    [message] = mailer.messages
    assert mailed_links(message, '/dashboard/') == {
        f'{ORIGIN}/dashboard/malaria-overview?source=new_dashboard_email'
    }


@pytest.mark.parametrize(
    'configured',
    ['https://harmony.example.org@attacker.invalid', 'http://harmony.example.org', ''],
)
def test_no_reset_mail_without_a_valid_configured_origin(
    app, mailer, monkeypatch, configured
):
    monkeypatch.setattr(app.zen_config.general, 'DEPLOYMENT_BASE_URL', configured)

    with pytest.raises(ValueError):
        _send_reset(app, monkeypatch, {})

    assert not mailer.messages
