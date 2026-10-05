"""WP-1h: the renderer's settings from its environment."""

import pytest

from harmony.worker.renderer.__main__ import settings_from_env


@pytest.fixture(autouse=True)
def fixture_clean_env(monkeypatch):
    for name in (
        'RENDERER_ALLOWED_ORIGIN',
        'RENDERER_EGRESS_PROXY',
        'RENDERER_MAP_ORIGINS',
        'RENDERER_BLOCKED_GRACE_SECONDS',
        'RENDERER_IGNORED_BLOCKED_HOSTS',
        'RENDERER_CLEANUP_GRACE_SECONDS',
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


def test_a_render_gets_ten_seconds_past_its_deadline_to_clean_up(monkeypatch):
    assert settings_from_env().cleanup_grace_seconds == 10.0

    monkeypatch.setenv('RENDERER_CLEANUP_GRACE_SECONDS', '4')

    assert settings_from_env().cleanup_grace_seconds == 4.0


def test_a_map_origin_that_is_not_a_bare_origin_stops_the_service(monkeypatch):
    monkeypatch.setenv('RENDERER_EGRESS_PROXY', 'http://render-egress:3128')
    monkeypatch.setenv('RENDERER_MAP_ORIGINS', 'https://api.mapbox.com/styles')

    with pytest.raises(ValueError):
        settings_from_env()


@pytest.mark.parametrize(
    'map_origin', ['http://web:8000', 'https://web', 'https://WEB:5443']
)
def test_a_map_origin_on_the_dashboards_host_stops_the_service(monkeypatch, map_origin):
    # Cookies are scoped to a host, not a port, so Chromium sends the render
    # token to any origin on the dashboard's host. Over https the proxy cannot
    # strip it from inside the tunnel.
    monkeypatch.setenv('RENDERER_EGRESS_PROXY', 'http://render-egress:3128')
    monkeypatch.setenv('RENDERER_ALLOWED_ORIGIN', 'http://web:5000')
    monkeypatch.setenv('RENDERER_MAP_ORIGINS', f'https://api.mapbox.com,{map_origin}')

    with pytest.raises(ValueError, match='dashboard'):
        settings_from_env()
