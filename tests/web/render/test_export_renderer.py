"""WP-1h: the render routes call the self-hosted renderer service (SEC-7, SEC-10).

`FakeRenderer` stands in for the service; nothing leaves the process.
"""

import dataclasses
import logging
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from render_fakes import (
    DASHBOARD_SLUG,
    SENDER,
    USERS,
    VIEW_DASHBOARD,
    FakeRenderResponse,
    _policy,
)
from web.server.redis import thumbnail_storage_service
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

    def post(url, json=None, timeout=None, stream=False):
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
    # The app logger propagates to the root logger caplog listens on (WP-2g).
    caplog.set_level(logging.INFO, logger='ZenysisLogger')
    return caplog


def test_a_failed_render_is_logged_without_the_token(
    client, renderer, monkeypatch, app_log
):
    _fail_with(monkeypatch, renderer, _response(status=504))

    client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(VIEWER))

    assert 'status 504' in app_log.text
    assert 'eyJ' not in app_log.text


@pytest.mark.parametrize(
    'body, logged',
    [
        (b'{"error": "egress_blocked"}', 'egress_blocked'),
        (b'{"error": "<script>"}', 'no error code'),
        (b'not json', 'no error code'),
        (b'{"error": "' + b'x' * 5000 + b'"}', 'no error code'),
    ],
    ids=['code', 'not-a-code', 'not-json', 'oversized'],
)
def test_a_renderer_failure_is_logged_with_its_error_code(
    client, renderer, monkeypatch, app_log, body, logged
):
    _fail_with(
        monkeypatch,
        renderer,
        _response(status=502, body=body, content_type='application/json'),
    )

    client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(VIEWER))

    [line] = [
        r.getMessage() for r in app_log.records if 'Renderer failed' in r.getMessage()
    ]
    assert line.endswith(f'status 502, application/json, {logged}')
    assert '<script>' not in line


def test_a_render_with_the_wrong_content_type_is_logged_as_such(
    client, renderer, monkeypatch, app_log
):
    _fail_with(monkeypatch, renderer, _response(content_type='text/html'))

    client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(VIEWER))

    [line] = [
        r.getMessage() for r in app_log.records if 'Renderer failed' in r.getMessage()
    ]
    assert line.endswith('status 200, text/html, not application/pdf')


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


# The policy pin through a real page load: the fake renderer loads the dashboard
# page with the minted token, so `on_identity_loaded` and `_install_token_needs`
# decide, as they do for the browser (review round 1, finding 6).


def test_a_render_whose_policy_is_unchanged_loads_the_page(client, renderer):
    renderer.load_page = True

    response = client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(NORTH))

    assert renderer.page_statuses == [200]
    assert response.status_code == 200
    assert response.data == f'render-as:{NORTH}'.encode()


def test_a_policy_change_while_the_render_is_queued_fails_the_page_load(
    client, renderer, monkeypatch
):
    def widen_norths_policy():
        monkeypatch.setitem(
            USERS,
            NORTH,
            dataclasses.replace(
                USERS[NORTH], provides=frozenset({VIEW_DASHBOARD, _policy()})
            ),
        )

    renderer.load_page = True
    renderer.before_page_load = widen_norths_policy

    response = client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(NORTH))

    assert renderer.page_statuses == [403]
    assert response.status_code == 500


def test_emailed_render_resolves_the_recipients_own_policy(app, renderer):
    # The sender is not the recipient, so no digest of the sender's policy is
    # pinned; the recipient's account decides when the page loads.
    with app.test_request_context('/', headers=SENDER):
        get_email_attachments(NORTH, SLUG, should_attach_pdf=True)

    [call] = renderer.calls
    assert call.identity == NORTH
    assert call.claims['query_needs'] == ['*']
    assert 'policy' not in call.claims


def test_emailed_render_with_a_failed_renderer_attaches_nothing(
    app, renderer, monkeypatch
):
    _fail_with(monkeypatch, renderer, requests.Timeout('read timed out'))

    with app.test_request_context('/', headers=SENDER):
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
        # Unicode digits: str.isdigit accepts them, int() does not.
        'width=%C2%B2&height=%D9%A3%D9%A3%D9%A3',
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


# One account's renders cannot fill the renderer's few slots (everyone else
# would queue behind them until their deadlines). Found by security review: the
# first cap left `/png/thumbnail`, which renders uncached on every call, and the
# thumbnail retrieve path uncapped.

VIEWER_ID = USERS[VIEWER].id
NORTH_ID = USERS[NORTH].id
CAPPED_ROUTES = [
    f'/dashboard/{SLUG}/pdf',
    f'/dashboard/{SLUG}/jpeg',
    f'/dashboard/{SLUG}/png/thumbnail',
]


def _fill_render_slots(app, account_id):
    # Literally the one slot an account has, so a larger cap fails these tests.
    app.cache.add(f'render-in-flight:{account_id}:0', True)


def _slots(app):
    return [key for key in app.cache.values if key.startswith('render-in-flight:')]


@pytest.mark.parametrize('route', CAPPED_ROUTES)
def test_a_render_beyond_the_accounts_in_flight_limit_is_a_503_without_a_render(
    app, client, renderer, route
):
    _fill_render_slots(app, VIEWER_ID)

    response = client.get(route, headers=as_user(VIEWER))

    assert response.status_code == 503
    assert renderer.calls == []
    assert not [key for key in app.cache.values if key.startswith('render-token:')]


def test_a_thumbnail_retrieve_beyond_the_limit_is_empty_and_not_cached(
    app, client, renderer, monkeypatch
):
    # Its wait for the slot is covered in test_render_slots.py.
    monkeypatch.setattr(thumbnail_storage_service, 'THUMBNAIL_SLOT_WAIT_SECONDS', 0)
    _fill_render_slots(app, VIEWER_ID)

    response = client.get(f'/api2/storage/retrieve?key={SLUG}', headers=as_user(VIEWER))

    assert response.status_code == 200
    assert response.get_json() == ''
    assert renderer.calls == []
    assert not [key for key in app.cache.values if key.startswith('thumbnail:')]


def test_an_emailed_render_counts_against_the_sender_not_the_recipient(
    app, renderer, monkeypatch
):
    # A share sends its notifications first, so a render that cannot get the
    # sender's slot within its wait fails like any other render, not a 503.
    clock = [0.0]
    monkeypatch.setattr(page_renderer.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(
        page_renderer.time,
        'sleep',
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    _fill_render_slots(app, NORTH_ID)

    with app.test_request_context('/', headers=as_user(NORTH)):
        app.preprocess_request()
        attachments = get_email_attachments(VIEWER, SLUG, should_attach_pdf=True)

    assert attachments == (None, None)
    assert renderer.calls == []
    assert clock[0] >= page_renderer.EMAIL_SLOT_WAIT_SECONDS


@pytest.mark.parametrize(
    'attach', [{'should_attach_pdf': True}, {'should_embed_image': True}]
)
def test_an_emailed_render_waits_for_the_senders_slot(
    app, renderer, monkeypatch, attach
):
    # Found in review round 2: with no wait, a share with an attachment mailed
    # without it whenever the sender had any render running.
    _fill_render_slots(app, NORTH_ID)
    waits = []

    def the_other_render_finishes(seconds):
        waits.append(seconds)
        app.cache.delete(f'render-in-flight:{NORTH_ID}:0')

    monkeypatch.setattr(page_renderer.time, 'sleep', the_other_render_finishes)

    with app.test_request_context('/', headers=as_user(NORTH)):
        app.preprocess_request()
        attachments, _ = get_email_attachments(VIEWER, SLUG, **attach)

    assert len(waits) == 1
    assert len(attachments) == 1
    assert renderer.calls[-1].identity == VIEWER


def test_one_accounts_renders_in_flight_do_not_hold_another(app, client, renderer):
    _fill_render_slots(app, VIEWER_ID)

    response = client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(NORTH))

    assert response.status_code == 200
    assert renderer.calls[-1].identity == NORTH


@pytest.mark.parametrize(
    'outcome',
    [requests.ConnectionError('renderer unreachable'), _response(status=504), None],
    ids=['unreachable', 'failed', 'rendered'],
)
@pytest.mark.parametrize('route', CAPPED_ROUTES)
def test_the_render_slot_is_released_when_the_render_returns(
    app, client, renderer, monkeypatch, outcome, route
):
    if outcome is not None:
        _fail_with(monkeypatch, renderer, outcome)

    client.get(route, headers=as_user(VIEWER))

    assert _slots(app) == []


def test_the_render_slot_is_held_by_the_account_for_the_render_deadline_only(
    app, client, renderer, monkeypatch
):
    held = {}
    add = app.cache.add

    def recording_add(key, value, timeout=None):
        if key.startswith('render-in-flight:'):
            held[key] = timeout
        return add(key, value, timeout)

    monkeypatch.setattr(app.cache, 'add', recording_add)

    client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(VIEWER))

    ttl = page_renderer.RENDER_TIMEOUT_SECONDS + page_renderer.RESPONSE_MARGIN_SECONDS
    assert held == {f'render-in-flight:{VIEWER_ID}:0': ttl}


# The web side reads at most RENDER_MAX_BYTES of the renderer's answer.


class _EndlessResponse(FakeRenderResponse):
    def __init__(self, content_length=None):
        super().__init__(b'', 'application/pdf')
        self.read = 0
        self.closed = False
        if content_length is not None:
            self.headers['Content-Length'] = str(content_length)

    @property
    def content(self):
        raise AssertionError('the whole body must never be loaded')

    @content.setter
    def content(self, _value):
        pass

    def iter_content(self, chunk_size):
        while True:
            self.read += chunk_size
            yield b'x' * chunk_size

    def close(self):
        self.closed = True


@pytest.mark.parametrize('content_length', [None, 10**9], ids=['unsized', 'sized'])
def test_an_oversized_answer_is_refused_without_reading_it_all(
    client, renderer, monkeypatch, content_length
):
    monkeypatch.setattr(page_renderer, 'RENDER_MAX_BYTES', 1024)
    endless = _EndlessResponse(content_length)
    _fail_with(monkeypatch, renderer, endless)

    response = client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(VIEWER))

    assert response.status_code == 500
    assert endless.read <= 1024 + page_renderer.READ_CHUNK_BYTES
    assert endless.closed
