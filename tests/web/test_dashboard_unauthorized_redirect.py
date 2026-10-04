from types import SimpleNamespace
from unittest import mock

from web.server.routes.dashboard import DashboardPageRouter
from web.server.routes.user_authentication import UserAuthenticationRouter


def test_signed_in_user_without_view_permission_is_sent_to_unauthorized_page(
    bare_flask_app,
):
    app = bare_flask_app()
    app.register_blueprint(UserAuthenticationRouter(None, 'en').generate_blueprint())
    app.register_blueprint(DashboardPageRouter(None, 'en').generate_blueprint())
    router = DashboardPageRouter(None, 'en')
    grid_dashboard = DashboardPageRouter.grid_dashboard.__wrapped__
    dashboard = SimpleNamespace(resource_id=7)

    with app.test_request_context('/dashboard/malaria?foo=1'), mock.patch(
        'web.server.routes.dashboard.get_dashboard', return_value=dashboard
    ), mock.patch(
        'web.server.routes.dashboard.is_authorized', return_value=False
    ), mock.patch(
        'web.server.routes.dashboard.current_user',
        SimpleNamespace(is_authenticated=True),
    ):
        response = grid_dashboard(router, name='malaria')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/unauthorized?foo=1')
