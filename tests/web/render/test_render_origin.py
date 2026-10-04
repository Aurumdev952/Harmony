"""WP-0i: renders and emailed links use the deployment's configured origin.

The app sets no SERVER_NAME, ProxyFix or trusted hosts, as in production, so a
request's Host header must never choose where a minted token is sent.
"""

import pytest
from flask import g

from tests.web.render.fakes import DASHBOARDS, DASHBOARD_SLUG, DEPLOYMENT_ORIGIN
from web.server.routes.views.dashboard import get_email_attachments, send_email

SLUG = DASHBOARD_SLUG
VIEWER = 'viewer@tests.invalid'
HOSTILE_HOSTS = ['attacker.invalid', 'real.org:@attacker.invalid']
PAGE = f'{DEPLOYMENT_ORIGIN}/dashboard/{SLUG}'


@pytest.fixture(autouse=True)
def fixture_no_server_name(app):
    assert app.config.get('SERVER_NAME') is None


@pytest.mark.parametrize('host', HOSTILE_HOSTS)
def test_render_route_sends_the_token_to_the_configured_origin(client, renderer, host):
    response = client.get(
        f'/dashboard/{SLUG}/pdf', headers={'Host': host, 'X-Test-User': VIEWER}
    )

    assert response.status_code == 200
    [call] = renderer.calls
    assert call.params['url'] == f'{PAGE}?screenshot=1&pdf=1'
    assert call.identity == VIEWER


@pytest.mark.parametrize('host', HOSTILE_HOSTS)
def test_thumbnail_retrieve_renders_the_configured_origin(client, renderer, host):
    response = client.get(
        f'/api2/storage/retrieve?key={SLUG}',
        headers={'Host': host, 'X-Test-User': VIEWER},
    )

    assert response.status_code == 200
    [call] = renderer.calls
    assert call.params['url'] == f'{PAGE}?screenshot=1&thumbnail=1'


@pytest.mark.parametrize('host', HOSTILE_HOSTS)
def test_emailed_render_sends_the_recipient_token_to_the_configured_origin(
    app, renderer, host
):
    with app.test_request_context('/', headers={'Host': host}):
        get_email_attachments(VIEWER, SLUG, should_attach_pdf=True)

    [call] = renderer.calls
    assert call.params['url'] == f'{PAGE}?screenshot=1&pdf=1'
    assert call.identity == VIEWER


class _EmailRecorder:
    def __init__(self):
        self.links = []

    def create_share_dashboard_pdf_message(self, *args, **kwargs):
        self.links.append(args[4])
        return 'message'

    def send_email(self, _message):
        return None


@pytest.mark.parametrize('host', HOSTILE_HOSTS)
def test_emailed_link_points_at_the_configured_origin(app, renderer, monkeypatch, host):
    recorder = _EmailRecorder()
    monkeypatch.setattr(app, 'email_renderer', recorder, raising=False)
    monkeypatch.setattr(app, 'notification_service', recorder, raising=False)

    with app.test_request_context('/', headers={'Host': host}):
        g.request_logger = app.logger
        send_email(
            VIEWER,
            DASHBOARDS[SLUG],
            ['recipient@tests.invalid'],
            'body',
            'subject',
            VIEWER,
        )

    assert recorder.links == [PAGE]
    assert renderer.calls == []
