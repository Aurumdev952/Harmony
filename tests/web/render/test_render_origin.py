"""WP-0i: renders and emailed links use the deployment's configured origin.

The app sets no SERVER_NAME, ProxyFix or trusted hosts, as in production, so
neither a request's Host header nor its script root may choose where a minted
token is sent. gunicorn 20.0.4 copies a `SCRIPT_NAME` request header into the
WSGI environ, so the script root is caller-controlled too.
"""

from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from flask import g

from render_fakes import DASHBOARDS, DASHBOARD_SLUG, DEPLOYMENT_ORIGIN
from web.server.routes.views.dashboard import get_email_attachments, send_email
from web.server.util.deployment_links import deployment_origin

SLUG = DASHBOARD_SLUG
VIEWER = 'viewer@tests.invalid'
HOSTILE_HOSTS = ['attacker.invalid', 'real.org:@attacker.invalid']
HOSTILE_SCRIPT_NAMES = ['@attacker.invalid', '.attacker.invalid', '/prefix']
PAGE = f'{DEPLOYMENT_ORIGIN}/dashboard/{SLUG}'


def _netloc(url):
    return urlsplit(url).netloc


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


@pytest.mark.parametrize('script_name', HOSTILE_SCRIPT_NAMES)
def test_render_route_ignores_the_request_script_root(client, renderer, script_name):
    response = client.get(
        f'/dashboard/{SLUG}/pdf',
        headers={'X-Test-User': VIEWER},
        environ_overrides={'SCRIPT_NAME': script_name},
    )

    assert response.status_code == 200
    [call] = renderer.calls
    assert call.params['url'] == f'{PAGE}?screenshot=1&pdf=1'
    assert _netloc(call.params['url']) == _netloc(DEPLOYMENT_ORIGIN)


@pytest.mark.parametrize('script_name', HOSTILE_SCRIPT_NAMES)
def test_thumbnail_retrieve_ignores_the_request_script_root(
    client, renderer, script_name
):
    response = client.get(
        f'/api2/storage/retrieve?key={SLUG}',
        headers={'X-Test-User': VIEWER},
        environ_overrides={'SCRIPT_NAME': script_name},
    )

    assert response.status_code == 200
    [call] = renderer.calls
    assert call.params['url'] == f'{PAGE}?screenshot=1&thumbnail=1'


@pytest.mark.parametrize('script_name', HOSTILE_SCRIPT_NAMES)
def test_emailed_render_ignores_the_request_script_root(app, renderer, script_name):
    with app.test_request_context('/', environ_overrides={'SCRIPT_NAME': script_name}):
        get_email_attachments(VIEWER, SLUG, should_attach_pdf=True)

    [call] = renderer.calls
    assert call.params['url'] == f'{PAGE}?screenshot=1&pdf=1'


@pytest.mark.parametrize('script_name', HOSTILE_SCRIPT_NAMES)
def test_emailed_link_ignores_the_request_script_root(
    app, renderer, monkeypatch, script_name
):
    recorder = _EmailRecorder()
    monkeypatch.setattr(app, 'email_renderer', recorder, raising=False)
    monkeypatch.setattr(app, 'notification_service', recorder, raising=False)

    with app.test_request_context('/', environ_overrides={'SCRIPT_NAME': script_name}):
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


@pytest.mark.parametrize(
    'configured, origin',
    [
        ('https://harmony.tests.invalid', 'https://harmony.tests.invalid'),
        ('https://harmony.tests.invalid/', 'https://harmony.tests.invalid'),
        ('https://harmony.tests.invalid:8443', 'https://harmony.tests.invalid:8443'),
        ('https://harmony_demo.zenysis.com', 'https://harmony_demo.zenysis.com'),
    ],
)
def test_configured_origin_is_accepted(configured, origin):
    assert deployment_origin(configured) == origin


@pytest.mark.parametrize(
    'configured',
    [
        None,
        '',
        'harmony.tests.invalid',
        '//harmony.tests.invalid',
        'http://harmony.tests.invalid',
        'javascript:alert(1)',
        'https://',
        'https://user@harmony.tests.invalid',
        'https://harmony.tests.invalid@attacker.invalid',
        'https://user:pass@harmony.tests.invalid',
        'https://harmony.tests.invalid/harmony',
        'https://harmony.tests.invalid?next=x',
        'https://harmony.tests.invalid#x',
        'https://harmony.tests.invalid:notaport',
    ],
)
def test_unusable_configured_origin_is_refused(configured):
    with pytest.raises(ValueError, match='DEPLOYMENT_BASE_URL'):
        deployment_origin(configured)


def test_render_with_an_unusable_configured_origin_makes_no_outbound_call(
    app, client, renderer, monkeypatch
):
    monkeypatch.setattr(
        app.zen_config.general,
        'DEPLOYMENT_BASE_URL',
        'https://harmony.tests.invalid@attacker.invalid',
    )
    monkeypatch.setitem(app.config, 'PROPAGATE_EXCEPTIONS', False)

    response = client.get(f'/dashboard/{SLUG}/pdf', headers={'X-Test-User': VIEWER})

    assert response.status_code == 500
    assert renderer.calls == []


@pytest.mark.parametrize(
    'configured, refused',
    [('https://harmony.tests.invalid', False), ('https://real@attacker.invalid', True)],
)
def test_app_startup_validates_the_configured_origin(configured, refused):
    # pylint: disable=import-outside-toplevel
    from web.server.app import validate_deployment_base_url

    general = SimpleNamespace(DEPLOYMENT_BASE_URL=configured)
    flask_app = SimpleNamespace(zen_config=SimpleNamespace(general=general))

    if refused:
        with pytest.raises(ValueError, match='DEPLOYMENT_BASE_URL'):
            validate_deployment_base_url(flask_app)
    else:
        validate_deployment_base_url(flask_app)


def test_gunicorn_app_refuses_an_unusable_origin_before_touching_the_database(
    monkeypatch,
):
    # pylint: disable=import-outside-toplevel
    from web.server import app as app_module

    monkeypatch.setenv('SERVER_SOFTWARE', 'gunicorn/20.0.4')
    monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', 'postgresql://tests@db.invalid/t')
    monkeypatch.setenv('JWT_SECRET_KEY', 'tests-web-jwt-key-' + 'k' * 32)
    load_config = app_module.initialize_zenysis_module

    def load_config_with_a_hostile_origin(app):
        load_config(app)
        monkeypatch.setattr(
            app.zen_config.general,
            'DEPLOYMENT_BASE_URL',
            'https://harmony.tests.invalid@attacker.invalid',
        )

    def touch_database(*_args, **_kwargs):
        raise AssertionError('the database was touched before the origin check')

    monkeypatch.setattr(
        app_module, 'initialize_zenysis_module', load_config_with_a_hostile_origin
    )
    monkeypatch.setattr(app_module, 'initialize_database_seed_values', touch_database)

    with pytest.raises(ValueError, match='DEPLOYMENT_BASE_URL'):
        app_module.create_app(zenysis_environment='harmony_demo', skip_db_check=True)
