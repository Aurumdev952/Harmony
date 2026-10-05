"""WP-1h: which requests the rendered page may make (SEC-10)."""

import pytest

from harmony.worker.renderer.egress import is_allowed, parse_origins

ORIGIN = 'http://web:5000'


@pytest.mark.parametrize(
    'url',
    [
        'http://web:5000/dashboard/malaria?screenshot=1',
        'http://web:5000/api2/dashboard/7',
        'http://web:5000/build/main.3f2a.js',
        'http://WEB:5000/api/query',
        'data:image/png;base64,iVBORw0KGgo=',
        'blob:http://web:5000/5f0c-1b2a',
        'about:blank',
    ],
)
def test_the_dashboards_own_origin_and_inline_urls_are_allowed(url):
    assert is_allowed(url, ORIGIN)


@pytest.mark.parametrize(
    'url',
    [
        'https://api.mapbox.com/styles/v1/mapbox/light-v10',
        'https://fonts.googleapis.com/css?family=Lato',
        'https://www.google-analytics.com/collect',
        'https://web:5000/api/query',
        'http://web:5001/',
        'http://web.attacker.invalid:5000/',
        'http://attacker.invalid/?u=http://web:5000/',
        'ws://web:5000/socket',
        'file:///etc/passwd',
        'blob:https://attacker.invalid/1',
        'http://169.254.169.254/latest/meta-data/',
        'http://[::1]:5000/',
        'http://[fd00:ec2::254]/latest/meta-data/',
        'http://[::ffff:169.254.169.254]/',
        'http://web:5000@attacker.invalid/',
        'http://attacker.invalid@web:5000/',
        'wss://web:5000/socket',
        'ftp://web:5000/',
        '',
    ],
)
def test_every_other_destination_is_blocked(url):
    assert not is_allowed(url, ORIGIN)


# Map styles and tiles (Mapbox today) are the one third party a dashboard page
# needs. They are fetched, never navigated to, and never get the cookie.

MAPS = ('https://api.mapbox.com',)


@pytest.mark.parametrize(
    'url',
    [
        'https://api.mapbox.com/styles/v1/mapbox/light-v10?access_token=pk.x',
        'https://API.mapbox.com:443/v4/mapbox.mapbox-streets-v8/1/0/0.vector.pbf',
    ],
)
def test_a_map_origin_may_be_fetched(url):
    assert is_allowed(url, ORIGIN, MAPS)


@pytest.mark.parametrize(
    'url',
    [
        'http://api.mapbox.com/styles/v1/mapbox/light-v10',
        'https://api.mapbox.com:8443/',
        'https://events.mapbox.com/events/v2',
        'https://api.mapbox.com.attacker.invalid/',
        'https://api.mapbox.com@attacker.invalid/',
        'wss://api.mapbox.com/',
    ],
)
def test_only_the_exact_map_origin_may_be_fetched(url):
    assert not is_allowed(url, ORIGIN, MAPS)


def test_a_map_origin_is_never_a_page_the_browser_may_navigate_to():
    assert not is_allowed('https://api.mapbox.com/', ORIGIN, MAPS, is_navigation=True)
    assert is_allowed('http://web:5000/dashboard/x', ORIGIN, MAPS, is_navigation=True)


def test_origin_lists_are_parsed_and_normalised():
    assert parse_origins(' https://API.mapbox.com , http://tiles.local:8080 ') == (
        'https://api.mapbox.com:443',
        'http://tiles.local:8080',
    )
    assert parse_origins('') == ()


@pytest.mark.parametrize(
    'value',
    [
        'api.mapbox.com',
        'https://api.mapbox.com/styles',
        'https://api.mapbox.com/?q=1',
        'https://user@api.mapbox.com',
        'ftp://api.mapbox.com',
        'https://',
    ],
)
def test_an_origin_list_entry_that_is_not_a_bare_origin_is_refused(value):
    with pytest.raises(ValueError):
        parse_origins(value)
