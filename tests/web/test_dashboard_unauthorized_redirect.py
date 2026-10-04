from types import SimpleNamespace
from unittest import mock

import pytest

from web.server.routes.dashboard import DashboardPageRouter
from web.server.routes.user_authentication import UserAuthenticationRouter


@pytest.mark.parametrize(
    'path, locale, expected_path',
    [
        ('/dashboard/malaria?foo=1', None, '/en/unauthorized'),
        ('/fr/dashboard/malaria', 'fr', '/fr/unauthorized'),
        # url_for control arguments in the query string must not reach url_for:
        # forwarding them let a link choose the redirect host.
        (
            '/dashboard/malaria?_external=1&_scheme=https://evil.example/x?',
            None,
            '/en/unauthorized',
        ),
        ('/dashboard/malaria?endpoint=x&_method=POST', None, '/en/unauthorized'),
    ],
)
def test_signed_in_user_without_view_permission_is_sent_to_unauthorized_page(
    bare_flask_app, path, locale, expected_path
):
    app = bare_flask_app()
    app.register_blueprint(UserAuthenticationRouter(None, 'en').generate_blueprint())
    app.register_blueprint(DashboardPageRouter(None, 'en').generate_blueprint())
    router = DashboardPageRouter(None, 'en')
    grid_dashboard = DashboardPageRouter.grid_dashboard.__wrapped__
    dashboard = SimpleNamespace(resource_id=7)

    with app.test_request_context(path, base_url='https://harmony.example'), mock.patch(
        'web.server.routes.dashboard.get_dashboard', return_value=dashboard
    ), mock.patch(
        'web.server.routes.dashboard.is_authorized', return_value=False
    ), mock.patch(
        'web.server.routes.dashboard.current_user',
        SimpleNamespace(is_authenticated=True),
    ):
        response = grid_dashboard(router, locale=locale, name='malaria')

    assert response.status_code == 302
    assert response.headers['Location'] in (
        expected_path,
        f'https://harmony.example{expected_path}',
    )
