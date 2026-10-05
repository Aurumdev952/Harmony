"""WP-0i: failed renders and stuck cache claims.

An unreachable urlbox must not put the request URL, which carries the urlbox API
key and the minted token, into any log (INV-6). These tests send real requests
to a closed loopback port; nothing leaves the host.
"""

import base64
import json
import logging
import socket

import pytest
import requests
from cachelib import FileSystemCache
from flask import Flask
from flask_caching import Cache

from log import LOG
from render_fakes import DASHBOARD_SLUG, DictCache
from web.server.redis import thumbnail_storage_service
from web.server.routes.views import page_renderer as page_renderer_views
from web.server.routes.views.dashboard import get_email_attachments

SLUG = DASHBOARD_SLUG
VIEWER = 'viewer@tests.invalid'
API_KEY = 'urlbox-key-that-must-not-be-logged'


@pytest.fixture(name='render_log')
def fixture_render_log(app, renderer, monkeypatch, caplog):
    monkeypatch.setattr(page_renderer_views.settings, 'URLBOX_API_KEY', API_KEY)
    # Production logs an unhandled exception instead of raising it into the test.
    monkeypatch.setitem(app.config, 'PROPAGATE_EXCEPTIONS', False)
    caplog.set_level(logging.DEBUG)
    LOG.addHandler(caplog.handler)
    yield caplog
    LOG.removeHandler(caplog.handler)


@pytest.fixture(name='unreachable_urlbox')
def fixture_unreachable_urlbox(render_log, monkeypatch):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    monkeypatch.setattr(page_renderer_views, 'requests', requests)
    monkeypatch.setattr(
        page_renderer_views, 'URLBOX_API_URL', f'http://127.0.0.1:{port}'
    )
    return render_log


def _logged(caplog) -> str:
    return '\n'.join(caplog.handler.format(record) for record in caplog.records)


def _assert_no_secrets_logged(caplog):
    logged = _logged(caplog)
    assert API_KEY not in logged
    assert 'accessKey' not in logged
    assert 'eyJ' not in logged  # the start of any JWT
    return logged


def _assert_failure_logged_without_secrets(caplog, output_format):
    logged = _assert_no_secrets_logged(caplog)
    assert f'Urlbox request for {output_format} of /dashboard/{SLUG} failed' in logged


@pytest.mark.parametrize(
    'path, output_format',
    [
        (f'/dashboard/{SLUG}/pdf', 'pdf'),
        (f'/dashboard/{SLUG}/jpeg', 'jpg'),
        (f'/api2/storage/retrieve?key={SLUG}', 'png'),
    ],
)
def test_urlbox_error_status_is_logged_without_secrets(
    client, renderer, render_log, path, output_format
):
    renderer.status_code = 500

    client.get(path, headers={'X-Test-User': VIEWER})

    [call] = renderer.calls
    assert API_KEY in call.url
    logged = _assert_no_secrets_logged(render_log)
    assert (
        f'Urlbox failed to generate {output_format} for /dashboard/{SLUG} '
        'with status code 500'
    ) in logged


def test_unreachable_urlbox_fails_the_render_route_without_logging_secrets(
    client, unreachable_urlbox
):
    response = client.get(f'/dashboard/{SLUG}/pdf', headers={'X-Test-User': VIEWER})

    assert response.status_code == 500
    _assert_failure_logged_without_secrets(unreachable_urlbox, 'pdf')


@pytest.mark.parametrize(
    'formats, output_format',
    [({'should_attach_pdf': True}, 'pdf'), ({'should_embed_image': True}, 'jpg')],
)
def test_unreachable_urlbox_fails_an_email_render_without_logging_secrets(
    app, unreachable_urlbox, formats, output_format
):
    with app.test_request_context('/'):
        app.preprocess_request()
        assert get_email_attachments(VIEWER, SLUG, **formats) == (None, None)

    _assert_failure_logged_without_secrets(unreachable_urlbox, output_format)


def test_unreachable_urlbox_fails_a_thumbnail_without_logging_secrets(
    app, client, unreachable_urlbox
):
    response = client.get(
        f'/api2/storage/retrieve?key={SLUG}', headers={'X-Test-User': VIEWER}
    )

    assert response.status_code == 200
    assert json.loads(response.data) == ''
    assert app.cache.values == {}
    _assert_failure_logged_without_secrets(unreachable_urlbox, 'png')


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
    [key] = cache.keys
    cache.set(key, 'stale-thumbnail', timeout=-1)  # still on disk, already expired

    response = client.get(url, headers=headers)

    assert response.status_code == 200
    assert base64.b64decode(json.loads(response.data)) == f'render-as:{VIEWER}'.encode()
    assert len(renderer.calls) == 2


class _BoundedDictCache(DictCache):
    """Fails the test instead of spinning forever."""

    def __init__(self):
        super().__init__()
        self.lookups = 0

    def _count(self):
        self.lookups += 1
        assert self.lookups < 20, 'the claim loop is spinning'

    def add(self, key, value, timeout=None):
        self._count()
        return super().add(key, value, timeout)

    def get(self, key):
        self._count()
        return super().get(key)


def test_claim_held_by_another_render_is_given_up_after_the_pending_timeout(
    app, client, renderer, monkeypatch
):
    monkeypatch.setattr(app, 'cache', _BoundedDictCache())
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


class _ClaimRaceCache(DictCache):
    """Redis between this caller's failed `add` and its `get`: the claim's holder
    failed and released it, and a third caller has already claimed it again.
    That third caller's render is stored by the time this caller looks again.
    """

    def __init__(self, stored):
        super().__init__()
        self.stored = stored
        self.lookups = 0
        self.deleted = []

    def add(self, key, value, timeout=None):
        if self.lookups == 0:
            return False  # the first holder's claim
        return super().add(key, value, timeout)

    def get(self, key):
        self.lookups += 1
        assert self.lookups < 20, 'the claim loop is spinning'
        if self.lookups == 1:
            self.values[key] = thumbnail_storage_service.PENDING
            return None
        self.values[key] = self.stored
        return self.stored

    def delete(self, key):
        self.deleted.append(key)
        super().delete(key)


def test_redis_miss_after_a_failed_claim_does_not_release_another_callers_claim(
    app, client, renderer, monkeypatch
):
    stored = base64.b64encode(b'render-by-the-third-caller').decode()
    cache = _ClaimRaceCache(stored)
    monkeypatch.setattr(app, 'cache', cache)
    monkeypatch.setattr(thumbnail_storage_service.time, 'sleep', lambda _seconds: None)

    response = client.get(
        f'/api2/storage/retrieve?key={SLUG}', headers={'X-Test-User': VIEWER}
    )

    assert response.status_code == 200
    assert json.loads(response.data) == stored
    assert cache.deleted == []
    assert renderer.calls == []


@pytest.mark.parametrize(
    'config, keeps_expired',
    [
        ({'CACHE_TYPE': 'FileSystemCache'}, True),
        ({'CACHE_TYPE': 'RedisCache', 'CACHE_REDIS_PORT': 1}, False),
    ],
)
def test_production_cache_backends_are_told_apart(tmp_path, config, keeps_expired):
    # The app's cache is a flask_caching.Cache wrapping a cachelib backend.
    app = Flask('tests.web', root_path=str(tmp_path), instance_path=str(tmp_path))
    cache = Cache(app, config={**config, 'CACHE_DIR': str(tmp_path)})

    with app.app_context():
        assert thumbnail_storage_service._keeps_expired_entries(cache) is keeps_expired
