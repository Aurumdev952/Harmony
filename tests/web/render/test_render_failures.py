"""WP-0i, WP-1h: failed renders and stuck cache claims.

An unreachable renderer must not put the minted token into any log (INV-6).
These tests send real requests to a closed loopback port; nothing leaves the
host.
"""

import base64
import json
import logging
import socket

import pytest
import requests
from cachelib import FileSystemCache

from log import LOG
from tests.web.render.fakes import DASHBOARD_SLUG
from web.server.redis import thumbnail_storage_service
from web.server.routes.views import page_renderer as page_renderer_views
from web.server.routes.views.dashboard import get_email_attachments

SLUG = DASHBOARD_SLUG
VIEWER = 'viewer@tests.invalid'


@pytest.fixture(name='unreachable_renderer')
def fixture_unreachable_renderer(app, renderer, monkeypatch, caplog):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    monkeypatch.setattr(page_renderer_views, 'requests', requests)
    monkeypatch.setattr(page_renderer_views, 'RENDERER_URL', f'http://127.0.0.1:{port}')
    # Production logs an unhandled exception instead of raising it into the test.
    monkeypatch.setitem(app.config, 'PROPAGATE_EXCEPTIONS', False)
    caplog.set_level(logging.DEBUG)
    LOG.addHandler(caplog.handler)
    yield caplog
    LOG.removeHandler(caplog.handler)


def _logged(caplog) -> str:
    return '\n'.join(caplog.handler.format(record) for record in caplog.records)


def _assert_failure_logged_without_secrets(caplog, output_format):
    logged = _logged(caplog)
    # Every minted token is a JWT, and every JWT starts with this header prefix.
    assert 'eyJ' not in logged
    assert (
        f'Renderer request for {output_format} of dashboard {SLUG} failed: '
        'ConnectionError'
    ) in logged


def test_unreachable_renderer_fails_the_render_route_without_logging_secrets(
    client, unreachable_renderer
):
    response = client.get(f'/dashboard/{SLUG}/pdf', headers={'X-Test-User': VIEWER})

    assert response.status_code == 500
    _assert_failure_logged_without_secrets(unreachable_renderer, 'pdf')


@pytest.mark.parametrize(
    'formats, output_format',
    [({'should_attach_pdf': True}, 'pdf'), ({'should_embed_image': True}, 'jpeg')],
)
def test_unreachable_renderer_fails_an_email_render_without_logging_secrets(
    app, unreachable_renderer, formats, output_format
):
    with app.test_request_context('/'):
        app.preprocess_request()
        assert get_email_attachments(VIEWER, SLUG, **formats) == (None, None)

    _assert_failure_logged_without_secrets(unreachable_renderer, output_format)


def test_unreachable_renderer_fails_a_thumbnail_without_logging_secrets(
    app, client, unreachable_renderer
):
    response = client.get(
        f'/api2/storage/retrieve?key={SLUG}', headers={'X-Test-User': VIEWER}
    )

    assert response.status_code == 200
    assert json.loads(response.data) == ''
    assert app.cache.values == {}
    _assert_failure_logged_without_secrets(unreachable_renderer, 'png')


class _BoundedFileSystemCache(FileSystemCache):
    """A real FileSystemCache that records its keys and fails the test instead of
    spinning forever.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.adds = 0
        self.keys = set()

    def add(self, key, value, timeout=None):
        self.adds += 1
        assert self.adds < 20, 'the claim loop is spinning'
        return super().add(key, value, timeout)

    def set(self, key, value, timeout=None, mgmt_element=False):
        if not mgmt_element:
            self.keys.add(key)
        return super().set(key, value, timeout, mgmt_element)


def test_expired_file_cache_entry_is_rendered_again(
    app, client, renderer, monkeypatch, tmp_path
):
    cache = _BoundedFileSystemCache(str(tmp_path))
    monkeypatch.setattr(app, 'cache', cache)
    monkeypatch.setattr(thumbnail_storage_service.time, 'sleep', lambda _seconds: None)
    headers = {'X-Test-User': VIEWER}
    url = f'/api2/storage/retrieve?key={SLUG}'
    client.get(url, headers=headers)
    [key] = [key for key in cache.keys if key.startswith('thumbnail:')]
    cache.set(key, 'stale-thumbnail', timeout=-1)  # still on disk, already expired

    response = client.get(url, headers=headers)

    assert response.status_code == 200
    assert base64.b64decode(json.loads(response.data)) == f'render-as:{VIEWER}'.encode()
    assert len(renderer.calls) == 2


def test_claim_held_by_another_render_is_given_up_after_the_pending_timeout(
    app, client, renderer, monkeypatch
):
    headers = {'X-Test-User': VIEWER}
    url = f'/api2/storage/retrieve?key={SLUG}'
    client.get(url, headers=headers)
    [key] = app.cache.values
    app.cache.values[key] = thumbnail_storage_service.PENDING
    monkeypatch.setattr(thumbnail_storage_service, 'PENDING_STATE_TIMEOUT', 0)
    monkeypatch.setattr(thumbnail_storage_service.time, 'sleep', lambda _seconds: None)

    response = client.get(url, headers=headers)

    assert response.status_code == 200
    assert json.loads(response.data) == ''
    assert len(renderer.calls) == 1
