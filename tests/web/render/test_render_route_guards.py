"""WP-0i: the dashboard render routes and the thumbnail cache (N1, N2, N7).

The call to the renderer service is replaced by `FakeRenderer`; nothing leaves the
process.
"""
import base64
import json

import pytest

from tests.web.render.fakes import (
    DASHBOARDS,
    DASHBOARD_SLUG,
    FakeDashboard,
    FakeRenderResponse,
)
from web.server.routes.views.dashboard import get_email_attachments

SLUG = DASHBOARD_SLUG
RENDER_ROUTES = [
    f'/dashboard/{SLUG}/pdf',
    f'/fr/dashboard/{SLUG}/pdf',
    f'/dashboard/{SLUG}/a1b2c3/pdf',
    f'/fr/dashboard/{SLUG}/a1b2c3/pdf',
    f'/dashboard/{SLUG}/jpeg',
    f'/fr/dashboard/{SLUG}/jpeg',
    f'/dashboard/{SLUG}/a1b2c3/jpeg',
    f'/fr/dashboard/{SLUG}/a1b2c3/jpeg',
    f'/dashboard/{SLUG}/png/thumbnail',
    f'/fr/dashboard/{SLUG}/png/thumbnail',
]

VIEWER = 'viewer@tests.invalid'
OUTSIDER = 'outsider@tests.invalid'
ADMIN = 'admin@tests.invalid'
NORTH = 'north@tests.invalid'
NORTH_2 = 'north2@tests.invalid'
SOUTH = 'south@tests.invalid'


def as_user(username):
    return {'X-Test-User': username}


def retrieve_thumbnail(client, username, query=''):
    response = client.get(
        f'/api2/storage/retrieve?key={SLUG}{query}', headers=as_user(username)
    )
    assert response.status_code == 200, response.data
    return base64.b64decode(json.loads(response.data)).decode()


@pytest.mark.parametrize('route', RENDER_ROUTES)
def test_anonymous_render_is_refused_without_an_outbound_call(client, renderer, route):
    response = client.get(route)

    assert response.status_code == 401
    assert renderer.calls == []


@pytest.mark.parametrize('route', RENDER_ROUTES)
def test_public_access_does_not_open_the_render_routes(
    client, renderer, public_access, route
):
    public_access['enabled'] = True

    response = client.get(route)

    assert response.status_code == 401
    assert renderer.calls == []


@pytest.mark.parametrize('route', RENDER_ROUTES)
def test_caller_without_view_resource_is_forbidden_without_an_outbound_call(
    client, renderer, route
):
    response = client.get(route, headers=as_user(OUTSIDER))

    assert response.status_code == 403
    assert renderer.calls == []


@pytest.mark.parametrize('route', RENDER_ROUTES)
def test_viewer_gets_a_render_made_as_themselves(client, renderer, route):
    response = client.get(route, headers=as_user(VIEWER))

    assert response.status_code == 200
    assert response.data == f'render-as:{VIEWER}'.encode()
    [call] = renderer.calls
    assert call.identity == VIEWER
    assert call.claims['needs'] == [['view_resource', 7, 'dashboard']]


@pytest.mark.parametrize('route', RENDER_ROUTES)
def test_request_args_cannot_redirect_the_minted_token(client, renderer, route):
    response = client.get(
        f'{route}?url=https://attacker.invalid/&cookie=accessKey=planted&force=false',
        headers=as_user(VIEWER),
    )

    assert response.status_code == 200
    [call] = renderer.calls
    assert set(call.params) == {
        'url',
        'token',
        'format',
        'viewport',
        'full_page',
        'pdf',
        'timeout_seconds',
    }
    assert call.params['url'].startswith('http://web:5000/')
    assert call.params['url'].split('?')[0].endswith(f'/dashboard/{SLUG}')
    assert call.identity == VIEWER


def test_missing_dashboard_is_not_found_for_a_signed_in_caller(client, renderer):
    response = client.get('/dashboard/no-such-dashboard/pdf', headers=as_user(VIEWER))

    assert response.status_code == 404
    assert renderer.calls == []


def test_missing_dashboard_does_not_reveal_itself_to_an_anonymous_caller(
    client, renderer
):
    response = client.get('/dashboard/no-such-dashboard/png/thumbnail')

    assert response.status_code == 401
    assert renderer.calls == []


def test_thumbnail_retrieve_refuses_an_anonymous_caller(client, renderer):
    response = client.get(f'/api2/storage/retrieve?key={SLUG}')

    assert response.status_code == 401
    assert renderer.calls == []


def test_thumbnail_retrieve_refuses_a_caller_without_view_resource(client, renderer):
    response = client.get(
        f'/api2/storage/retrieve?key={SLUG}', headers=as_user(OUTSIDER)
    )

    assert response.status_code in (401, 403)
    assert renderer.calls == []


def test_thumbnail_is_rendered_as_the_requesting_viewer(client, renderer):
    assert retrieve_thumbnail(client, VIEWER) == f'render-as:{VIEWER}'
    [call] = renderer.calls
    assert call.identity == VIEWER


@pytest.mark.parametrize('wider', [VIEWER, ADMIN])
def test_restricted_viewer_never_receives_a_thumbnail_rendered_under_a_wider_policy(
    client, renderer, wider
):
    retrieve_thumbnail(client, wider)

    assert retrieve_thumbnail(client, NORTH) == f'render-as:{NORTH}'
    assert [call.identity for call in renderer.calls] == [wider, NORTH]


def test_viewers_with_different_restrictions_get_their_own_thumbnails(client, renderer):
    assert retrieve_thumbnail(client, NORTH) == f'render-as:{NORTH}'
    assert retrieve_thumbnail(client, SOUTH) == f'render-as:{SOUTH}'


def test_viewers_with_the_same_policy_share_one_render(client, renderer):
    first = retrieve_thumbnail(client, NORTH)
    second = retrieve_thumbnail(client, NORTH_2)

    assert first == second == f'render-as:{NORTH}'
    assert len(renderer.calls) == 1


def test_thumbnail_retrieve_args_cannot_redirect_the_minted_token(client, renderer):
    retrieve_thumbnail(client, VIEWER, '&url=https://attacker.invalid/')

    [call] = renderer.calls
    assert call.params['url'].split('?')[0].endswith(f'/dashboard/{SLUG}')


def test_failed_thumbnail_render_does_not_leave_the_cache_pending(
    app, client, renderer, monkeypatch
):
    failed = FakeRenderResponse(b'')
    failed.status_code = 500
    monkeypatch.setattr(renderer, 'post', lambda *args, **kwargs: failed)

    assert retrieve_thumbnail(client, VIEWER) == ''
    assert 'PENDING' not in app.cache.values.values()


def test_thumbnail_retrieve_refuses_an_anonymous_caller_under_public_access(
    client, renderer, public_access
):
    public_access['enabled'] = True

    response = client.get(
        f'/api2/storage/retrieve?key={SLUG}',
        headers={'Referer': f'http://harmony.tests.invalid/dashboard/{SLUG}'},
    )

    assert response.status_code == 401
    assert renderer.calls == []


def test_slug_spelt_in_another_case_reuses_the_cached_thumbnail(client, renderer):
    retrieve_thumbnail(client, NORTH)

    response = client.get(
        f'/api2/storage/retrieve?key={SLUG.upper()}', headers=as_user(NORTH)
    )

    assert response.status_code == 200
    assert len(renderer.calls) == 1


def test_slug_reused_by_another_dashboard_does_not_serve_the_old_thumbnail(
    client, renderer, monkeypatch
):
    retrieve_thumbnail(client, ADMIN)
    monkeypatch.setitem(DASHBOARDS, SLUG, FakeDashboard(SLUG, 8))

    retrieve_thumbnail(client, ADMIN)

    assert len(renderer.calls) == 2


@pytest.mark.parametrize(
    'link, page',
    [
        (
            'https://attacker.invalid/fr/dashboard/elsewhere#h=a1b2c3',
            f'http://web:5000/fr/dashboard/{SLUG}?screenshot=1&pdf=1#h=a1b2c3',
        ),
        (
            'https://attacker.invalid/steal',
            f'http://web:5000/dashboard/{SLUG}?screenshot=1&pdf=1',
        ),
        (None, f'http://web:5000/dashboard/{SLUG}?screenshot=1&pdf=1'),
    ],
)
def test_emailed_render_loads_this_apps_dashboard_whatever_link_is_sent(
    app, renderer, link, page
):
    with app.test_request_context('/'):
        get_email_attachments(VIEWER, SLUG, should_attach_pdf=True, dashboard_url=link)

    [call] = renderer.calls
    assert call.params['url'] == page
    assert call.identity == VIEWER
