"""WP-1h: which requests the rendered page may make (SEC-10)."""
import pytest

from harmony.worker.renderer.egress import is_allowed

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
        '',
    ],
)
def test_every_other_destination_is_blocked(url):
    assert not is_allowed(url, ORIGIN)
