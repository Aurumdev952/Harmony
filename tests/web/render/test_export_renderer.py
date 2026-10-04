"""WP-1h: the render routes call the self-hosted renderer service (SEC-7, SEC-10).

`FakeRenderer` stands in for the service; nothing leaves the process.
"""
import logging
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from tests.web.render.fakes import DASHBOARD_SLUG, FakeRenderResponse
from web.server.routes.views import page_renderer
from web.server.routes.views.dashboard import get_email_attachments

SLUG = DASHBOARD_SLUG
VIEWER = 'viewer@tests.invalid'
NORTH = 'north@tests.invalid'
NORTH_2 = 'north2@tests.invalid'
SOUTH = 'south@tests.invalid'

PDF = ('pdf', 'application/pdf')
JPEG = ('jpeg', 'image/jpeg')
PNG = ('png', 'image/png')
ROUTES = [
    (f'/dashboard/{SLUG}/pdf', PDF),
    (f'/fr/dashboard/{SLUG}/a1b2c3/pdf', PDF),
    (f'/dashboard/{SLUG}/jpeg', JPEG),
    (f'/fr/dashboard/{SLUG}/a1b2c3/jpeg', JPEG),
    (f'/dashboard/{SLUG}/png/thumbnail', PNG),
]
ROUTE_PATHS = [route for route, _ in ROUTES]


def as_user(username):
    return {'X-Test-User': username}


def render(client, renderer, route, username=VIEWER):
    response = client.get(route, headers=as_user(username))
    return response, renderer.calls[-1] if renderer.calls else None


@pytest.mark.parametrize('route', ROUTE_PATHS)
def test_render_goes_to_the_renderer_service_and_nowhere_else(client, renderer, route):
    response, call = render(client, renderer, route)

    assert response.status_code == 200
    assert call.url == 'http://renderer:8080/render'
    page = urlsplit(call.params['url'])
    assert (page.scheme, page.netloc) == ('http', 'web:5000')
    assert page.path.endswith(f'/dashboard/{SLUG}')


@pytest.mark.parametrize('route', ROUTE_PATHS)
def test_render_url_never_uses_the_public_host(client, renderer, route):
    # The test app serves as harmony.tests.invalid. urlbox fetched that public
    # URL; the renderer loads the dashboard over the internal network only.
    _, call = render(client, renderer, route)

    assert 'harmony.tests.invalid' not in call.params['url']


@pytest.mark.parametrize('route, expected', ROUTES)
def test_each_route_asks_for_its_format_and_answers_with_its_content_type(
    client, renderer, route, expected
):
    output_format, content_type = expected

    response, call = render(client, renderer, route)

    assert call.params['format'] == output_format
    assert response.headers['Content-Type'] == content_type
    assert response.data == f'render-as:{VIEWER}'.encode()


def test_pdf_render_loads_the_print_layout(client, renderer):
    _, call = render(client, renderer, f'/fr/dashboard/{SLUG}/a1b2c3/pdf')

    page = urlsplit(call.params['url'])
    assert page.path == f'/fr/dashboard/{SLUG}'
    assert parse_qs(page.query) == {'screenshot': ['1'], 'pdf': ['1']}
    assert page.fragment == 'h=a1b2c3'
    assert call.params['pdf'] == {'page_size': 'A4', 'landscape': False}


def test_thumbnail_render_loads_the_thumbnail_layout_at_the_urlbox_viewport(
    client, renderer
):
    _, call = render(client, renderer, f'/dashboard/{SLUG}/png/thumbnail')

    assert parse_qs(urlsplit(call.params['url']).query) == {
        'screenshot': ['1'],
        'thumbnail': ['1'],
    }
    assert call.params['viewport'] == {'width': 1280, 'height': 1024}
    assert call.params['full_page'] is False


def test_jpeg_render_captures_the_full_page_at_1280_wide(client, renderer):
    _, call = render(client, renderer, f'/dashboard/{SLUG}/jpeg')

    assert call.params['viewport']['width'] == 1280
    assert call.params['full_page'] is True


@pytest.mark.parametrize('route', ROUTE_PATHS)
def test_token_is_live_during_the_render_and_refused_after_it(
    app, client, renderer, route
):
    render(client, renderer, route)

    [call] = renderer.calls
    assert call.token_was_live
    assert not [key for key in app.cache.values if key.startswith('render-token:')]


@pytest.mark.parametrize('route', ROUTE_PATHS)
def test_token_outlives_the_render_deadline_and_the_call_is_bounded(
    client, renderer, route
):
    _, call = render(client, renderer, route)

    deadline = call.params['timeout_seconds']
    assert 0 < deadline <= 120
    connect_timeout, read_timeout = call.timeout
    assert connect_timeout <= 10
    assert deadline < read_timeout <= deadline + 30
    assert call.token_lifetime >= read_timeout


def _fail_with(monkeypatch, renderer, outcome):
    calls = []

    def post(url, json=None, timeout=None):
        calls.append(json)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(renderer, 'post', post)
    return calls


def _response(status=200, body=b'%PDF-1.7', content_type='application/pdf'):
    response = FakeRenderResponse(body, content_type)
    response.status_code = status
    return response


@pytest.mark.parametrize(
    'outcome',
    [
        requests.Timeout('read timed out'),
        requests.ConnectionError('renderer unreachable'),
        _response(status=504),
        _response(status=503),
        _response(content_type='text/html'),
    ],
    ids=['timeout', 'unreachable', 'render-deadline', 'busy', 'wrong-content-type'],
)
def test_a_failed_render_is_a_500_and_its_token_is_revoked(
    app, client, renderer, monkeypatch, outcome
):
    calls = _fail_with(monkeypatch, renderer, outcome)

    response = client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(VIEWER))

    assert response.status_code == 500
    assert len(calls) == 1
    assert not [key for key in app.cache.values if key.startswith('render-token:')]


def test_output_over_the_size_limit_is_refused(client, renderer, monkeypatch):
    monkeypatch.setattr(page_renderer, 'RENDER_MAX_BYTES', 8)
    _fail_with(monkeypatch, renderer, _response(body=b'%PDF-' + b'x' * 8))

    response = client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(VIEWER))

    assert response.status_code == 500


@pytest.fixture(name='app_log')
def fixture_app_log(caplog):
    # The app logger does not propagate to the root logger caplog listens on.
    logger = logging.getLogger('ZenysisLogger')
    logger.addHandler(caplog.handler)
    yield caplog
    logger.removeHandler(caplog.handler)


def test_a_failed_render_is_logged_without_the_token(
    client, renderer, monkeypatch, app_log
):
    _fail_with(monkeypatch, renderer, _response(status=504))

    client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(VIEWER))

    assert 'status 504' in app_log.text
    assert 'eyJ' not in app_log.text


def test_restricted_viewer_render_carries_their_policy(client, renderer):
    _, north = render(client, renderer, f'/dashboard/{SLUG}/pdf', NORTH)
    _, north_2 = render(client, renderer, f'/dashboard/{SLUG}/pdf', NORTH_2)
    _, south = render(client, renderer, f'/dashboard/{SLUG}/pdf', SOUTH)
    _, viewer = render(client, renderer, f'/dashboard/{SLUG}/pdf', VIEWER)

    assert north.identity == NORTH
    assert north.claims['needs'] == [['view_resource', 7, 'dashboard']]
    assert north.claims['query_needs'] == ['*']
    assert north.claims['policy'] == north_2.claims['policy']
    assert north.claims['policy'] not in (
        south.claims['policy'],
        viewer.claims['policy'],
    )


def test_emailed_render_resolves_the_recipients_own_policy(app, renderer):
    # The sender is not the recipient, so no digest of the sender's policy is
    # pinned; the recipient's account decides when the page loads.
    with app.test_request_context('/'):
        get_email_attachments(NORTH, SLUG, should_attach_pdf=True)

    [call] = renderer.calls
    assert call.identity == NORTH
    assert call.claims['query_needs'] == ['*']
    assert 'policy' not in call.claims


def test_emailed_render_with_a_failed_renderer_attaches_nothing(
    app, renderer, monkeypatch
):
    _fail_with(monkeypatch, renderer, requests.Timeout('read timed out'))

    with app.test_request_context('/'):
        assert get_email_attachments(NORTH, SLUG, should_attach_pdf=True) == (
            None,
            None,
        )


def test_supported_request_args_shape_the_render(client, renderer):
    _, call = render(
        client,
        renderer,
        f'/dashboard/{SLUG}/pdf?width=1600&height=900&full_page=true'
        '&pdf_page_size=Letter&pdf_orientation=landscape',
    )

    assert call.params['viewport'] == {'width': 1600, 'height': 900}
    assert call.params['full_page'] is True
    assert call.params['pdf'] == {'page_size': 'Letter', 'landscape': True}


@pytest.mark.parametrize(
    'query',
    [
        'width=99999&height=-1',
        'width=abc&height=1e9',
        'pdf_page_size=../../etc&pdf_orientation=sideways',
        'delay=60000&wait_timeout=999999&url=https://attacker.invalid/',
    ],
)
def test_unsupported_or_out_of_range_args_fall_back_to_the_defaults(
    client, renderer, query
):
    _, call = render(client, renderer, f'/dashboard/{SLUG}/pdf?{query}')

    assert call.params['viewport'] == {'width': 1280, 'height': 1024}
    assert call.params['pdf'] == {'page_size': 'A4', 'landscape': False}
    assert urlsplit(call.params['url']).netloc == 'web:5000'
    assert call.params['timeout_seconds'] <= 120


def test_thumbnail_ignores_request_args(client, renderer):
    _, call = render(
        client, renderer, f'/dashboard/{SLUG}/png/thumbnail?width=1600&full_page=true'
    )

    assert call.params['viewport'] == {'width': 1280, 'height': 1024}
    assert call.params['full_page'] is False
