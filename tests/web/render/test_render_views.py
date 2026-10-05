"""WP-1h: a render's page load is not a dashboard view (WP-0i carried risk 5).

Renders used to sign in as the render bot, which `track_dashboard_access` skips.
They now sign in as the requesting user, so without this every export would
count as that user viewing the dashboard.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from flask import Flask
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    verify_jwt_in_request_optional,
)

from tests.web.render.fakes import DictCache
from web.server.api import dashboard_api_models
from web.server.security.render_tokens import render_token

USERNAME = 'north@tests.invalid'


@pytest.fixture(name='app')
def fixture_app(bare_flask_app) -> Flask:
    app = bare_flask_app()
    app.config.update(
        JWT_SECRET_KEY='tests-web-placeholder-jwt-key',
        JWT_TOKEN_LOCATION=['cookies'],
        JWT_ACCESS_COOKIE_NAME='accessKey',
        JWT_CSRF_METHODS=[],
    )
    JWTManager(app)
    app.cache = DictCache()
    return app


@pytest.fixture(name='tracked')
def fixture_tracked(monkeypatch) -> list:
    tracked: list = []
    monkeypatch.setattr(
        dashboard_api_models,
        'track_dashboard_access',
        lambda dashboard_id: tracked.append(dashboard_id),
    )
    return tracked


def _page_load(app: Flask, token: str, dashboard) -> None:
    with app.test_request_context('/', headers={'Cookie': f'accessKey={token}'}):
        verify_jwt_in_request_optional()
        dashboard_api_models.record_dashboard_view(dashboard)


def test_a_render_page_load_does_not_count_as_a_view(app, tracked):
    dashboard = SimpleNamespace(id=3, total_views=5)

    with (
        app.test_request_context('/'),
        render_token(USERNAME, 7, policy=None, ttl_seconds=60) as token,
    ):
        _page_load(app, token, dashboard)

    assert dashboard.total_views == 5
    assert tracked == []


def test_a_signed_in_users_page_load_counts_as_a_view(app, tracked):
    dashboard = SimpleNamespace(id=3, total_views=5)
    with app.test_request_context('/'):
        token = create_access_token(identity=USERNAME, expires_delta=timedelta(60))

    _page_load(app, token, dashboard)

    assert dashboard.total_views == 6
    assert tracked == [3]
