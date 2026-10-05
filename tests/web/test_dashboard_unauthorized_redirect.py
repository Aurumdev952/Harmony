from types import SimpleNamespace
from unittest import mock

import pytest

from web.server.routes.dashboard import DashboardPageRouter
from web.server.routes.user_authentication import UserAuthenticationRouter

HOST = 'https://harmony.example'


@pytest.mark.parametrize(
    'path, expected_location',
    [
        ('/dashboard/malaria?foo=1', f'{HOST}/en/unauthorized'),
        ('/fr/dashboard/malaria', f'{HOST}/fr/unauthorized'),
        # url_for control arguments in the query string must not reach url_for:
        # forwarding them let a link choose the redirect host.
        (
            '/dashboard/malaria?_external=1&_scheme=https://evil.example/x?',
            f'{HOST}/en/unauthorized',
        ),
        ('/dashboard/malaria?endpoint=x&_method=POST', f'{HOST}/en/unauthorized'),
    ],
)
def test_signed_in_user_without_view_permission_is_sent_to_unauthorized_page(
    bare_flask_app, path, expected_location
):
    app = bare_flask_app()
    app.register_blueprint(UserAuthenticationRouter(None, 'en').generate_blueprint())
    app.register_blueprint(DashboardPageRouter(None, 'en').generate_blueprint())
    signed_in = SimpleNamespace(is_authenticated=True)

    with (
        mock.patch(
            'web.server.routes.dashboard.get_dashboard',
            return_value=SimpleNamespace(resource_id=7),
        ),
        mock.patch('web.server.routes.dashboard.is_authorized', return_value=False),
        mock.patch('web.server.routes.dashboard.current_user', signed_in),
        mock.patch('web.server.routes.views.authentication.current_user', signed_in),
        mock.patch(
            'web.server.routes.views.authentication.get_user_string', lambda user: 'u'
        ),
        mock.patch(
            'web.server.routes.views.authentication.get_configuration',
            return_value=False,
        ),
    ):
        response = app.test_client().get(path, base_url=HOST)

    assert response.status_code == 302
    assert response.headers['Location'] == expected_location
