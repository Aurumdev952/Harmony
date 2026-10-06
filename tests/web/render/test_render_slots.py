"""WP-1h round 2: how an account's render slot is claimed, waited for and freed.

Found in review: the slot claim was SETNX then EXPIRE on Redis, so a failure
between the two left a slot that never expired; a FileSystemCache never gave an
expired slot back; and Overview thumbnails gave up at once while another render
of the same account ran.
"""

import base64
import json
from typing import Dict, List

import pytest
from cachelib import FileSystemCache, RedisCache

from render_fakes import DASHBOARD_SLUG, USERS, FakeRedis
from web.server.redis import thumbnail_storage_service
from web.server.routes.views import page_renderer

SLUG = DASHBOARD_SLUG
VIEWER = 'viewer@tests.invalid'
VIEWER_ID = USERS[VIEWER].id
SLOT = f'render-in-flight:{VIEWER_ID}:0'


def as_user(username: str) -> Dict[str, str]:
    return {'X-Test-User': username}


@pytest.fixture(name='fake_redis')
def fixture_fake_redis(app, renderer, monkeypatch) -> FakeRedis:
    client = FakeRedis()
    monkeypatch.setattr(app, 'cache', RedisCache(host=client, key_prefix='zen-test-'))
    return client


@pytest.mark.parametrize(
    'path',
    [f'/dashboard/{SLUG}/pdf', f'/api2/storage/retrieve?key={SLUG}'],
    ids=['export', 'thumbnail'],
)
def test_every_claim_on_redis_sets_its_expiry_in_the_same_command(
    client, renderer, fake_redis, path
):
    response = client.get(path, headers=as_user(VIEWER))

    assert response.status_code == 200
    assert renderer.calls
    assert not [c for c in fake_redis.commands if c[0] in ('setnx', 'expire')]
    assert [name for name, ttl in fake_redis.ttls.items() if ttl is None] == []


def test_a_held_slot_on_redis_is_a_503_without_a_render(client, renderer, fake_redis):
    fake_redis.values[f'zen-test-{SLOT}'] = b'!\x80\x04\x88.'

    response = client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(VIEWER))

    assert response.status_code == 503
    assert renderer.calls == []


def test_an_expired_slot_on_a_file_cache_is_given_back(
    app, client, renderer, monkeypatch, tmp_path
):
    cache = FileSystemCache(str(tmp_path))
    monkeypatch.setattr(app, 'cache', cache)
    cache.set(SLOT, True, timeout=-1)  # left by a dead worker, already expired

    response = client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(VIEWER))

    assert response.status_code == 200
    assert len(renderer.calls) == 1


def test_a_live_slot_on_a_file_cache_is_kept(
    app, client, renderer, monkeypatch, tmp_path
):
    cache = FileSystemCache(str(tmp_path))
    monkeypatch.setattr(app, 'cache', cache)
    cache.set(SLOT, True, timeout=300)

    response = client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(VIEWER))

    assert response.status_code == 503
    assert renderer.calls == []


def test_a_thumbnail_waits_for_the_accounts_slot_and_then_renders(
    app, client, renderer, monkeypatch
):
    app.cache.add(SLOT, True)
    waits: List[float] = []

    def the_other_render_finishes(seconds: float) -> None:
        waits.append(seconds)
        app.cache.delete(SLOT)

    monkeypatch.setattr(page_renderer.time, 'sleep', the_other_render_finishes)

    response = client.get(f'/api2/storage/retrieve?key={SLUG}', headers=as_user(VIEWER))

    assert base64.b64decode(json.loads(response.data)) == f'render-as:{VIEWER}'.encode()
    assert len(waits) == 1
    assert len(renderer.calls) == 1


def test_a_thumbnail_gives_up_after_its_wait_and_is_not_cached(
    app, client, renderer, monkeypatch
):
    app.cache.add(SLOT, True)
    clock = [0.0]
    monkeypatch.setattr(page_renderer.time, 'monotonic', lambda: clock[0])

    def tick(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(page_renderer.time, 'sleep', tick)

    response = client.get(f'/api2/storage/retrieve?key={SLUG}', headers=as_user(VIEWER))

    assert json.loads(response.data) == ''
    assert renderer.calls == []
    assert clock[0] >= thumbnail_storage_service.THUMBNAIL_SLOT_WAIT_SECONDS
    assert not [key for key in app.cache.values if key.startswith('thumbnail:')]


def test_an_export_does_not_wait_for_the_accounts_slot(
    app, client, renderer, monkeypatch
):
    app.cache.add(SLOT, True)
    monkeypatch.setattr(
        page_renderer.time, 'sleep', pytest.fail
    )  # an export answers 503 at once

    response = client.get(f'/dashboard/{SLUG}/pdf', headers=as_user(VIEWER))

    assert response.status_code == 503
