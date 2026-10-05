"""WP-1h: the renderer's settings from its environment."""

import pytest

from harmony.worker.renderer.__main__ import settings_from_env


@pytest.fixture(autouse=True)
def fixture_clean_env(monkeypatch):
    for name in (
        'RENDERER_EGRESS_PROXY',
        'RENDERER_MAP_ORIGINS',
        'RENDERER_BLOCKED_GRACE_SECONDS',
        'RENDERER_IGNORED_BLOCKED_HOSTS',
    ):
        monkeypatch.delenv(name, raising=False)


def test_without_an_egress_proxy_no_map_origin_is_reachable():
    settings = settings_from_env()

    assert settings.egress_proxy is None
    assert settings.map_origins == ()


def test_with_an_egress_proxy_mapbox_is_the_default_map_origin(monkeypatch):
    monkeypatch.setenv('RENDERER_EGRESS_PROXY', 'http://render-egress:3128')

    settings = settings_from_env()

    assert settings.egress_proxy == 'http://render-egress:3128'
    assert settings.map_origins == ('https://api.mapbox.com:443',)
    assert settings.ignored_blocked_hosts == ('events.mapbox.com',)
    assert settings.blocked_grace_seconds == 10.0


def test_map_origins_and_grace_are_configurable(monkeypatch):
    monkeypatch.setenv('RENDERER_EGRESS_PROXY', 'http://render-egress:3128')
    monkeypatch.setenv('RENDERER_MAP_ORIGINS', 'https://tiles.example.org')
    monkeypatch.setenv('RENDERER_BLOCKED_GRACE_SECONDS', '3')
    monkeypatch.setenv('RENDERER_IGNORED_BLOCKED_HOSTS', '')

    settings = settings_from_env()

    assert settings.map_origins == ('https://tiles.example.org:443',)
    assert settings.blocked_grace_seconds == 3.0
    assert settings.ignored_blocked_hosts == ()


def test_a_map_origin_that_is_not_a_bare_origin_stops_the_service(monkeypatch):
    monkeypatch.setenv('RENDERER_EGRESS_PROXY', 'http://render-egress:3128')
    monkeypatch.setenv('RENDERER_MAP_ORIGINS', 'https://api.mapbox.com/styles')

    with pytest.raises(ValueError):
        settings_from_env()
