"""WP-1h: what the renderer service accepts as a render request."""

import json

import pytest

from harmony.worker.renderer.spec import (
    InvalidRenderRequest,
    RenderSpec,
    Viewport,
    parse_render_request,
)

ORIGIN = 'http://web:5000'
TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJpZGVudGl0eSI6InRlc3QifQ.c2lnbmF0dXJl'
VALID = {
    'url': f'{ORIGIN}/dashboard/malaria?screenshot=1&pdf=1#h=a1b2c3',
    'token': TOKEN,
    'format': 'pdf',
    'viewport': {'width': 1280, 'height': 1024},
    'full_page': False,
    'pdf': {'page_size': 'A4', 'landscape': False},
    'timeout_seconds': 60,
}


def parse(overrides=None, drop=(), max_timeout_seconds=120.0):
    body = {**VALID, **(overrides or {})}
    for key in drop:
        body.pop(key)
    return parse_render_request(
        json.dumps(body).encode(),
        allowed_origin=ORIGIN,
        max_timeout_seconds=max_timeout_seconds,
    )


def test_a_valid_request_parses():
    assert parse() == RenderSpec(
        url=VALID['url'],
        token=TOKEN,
        format='pdf',
        viewport=Viewport(1280, 1024),
        full_page=False,
        pdf_page_size='A4',
        pdf_landscape=False,
        timeout_seconds=60.0,
    )


def test_optional_fields_take_their_defaults():
    spec = parse(
        {'format': 'png'}, drop=('viewport', 'full_page', 'pdf', 'timeout_seconds')
    )

    assert spec.viewport == Viewport(1280, 1024)
    assert spec.full_page is False
    assert (spec.pdf_page_size, spec.pdf_landscape) == ('A4', False)
    assert spec.timeout_seconds == 120.0


def test_timeout_is_capped_by_the_service():
    assert parse({'timeout_seconds': 600}, max_timeout_seconds=90).timeout_seconds == 90


@pytest.mark.parametrize(
    'url',
    [
        'http://attacker.invalid/dashboard/malaria',
        'https://web:5000/dashboard/malaria',
        'http://web:5001/dashboard/malaria',
        'http://web.attacker.invalid:5000/dashboard/malaria',
        'http://user:pass@web:5000/dashboard/malaria',
        'http://attacker.invalid@web:5000/dashboard/malaria',
        'http://web:5000@attacker.invalid/dashboard/malaria',
        'http://web:5000\\@attacker.invalid/dashboard/malaria',
        'http://169.254.169.254/latest/meta-data/',
        'http://[::1]:5000/dashboard/malaria',
        'http://[fd00:ec2::254]/latest/meta-data/',
        'http://[::ffff:169.254.169.254]/',
        'http://0x7f000001:5000/dashboard/malaria',
        'file:///etc/passwd',
        'javascript:alert(1)',
        'data:text/html,<h1>x</h1>',
        '//web:5000/dashboard/malaria',
        '/dashboard/malaria',
        '',
    ],
)
def test_only_the_allowed_origin_may_be_rendered(url):
    with pytest.raises(InvalidRenderRequest):
        parse({'url': url})


@pytest.mark.parametrize(
    'overrides',
    [
        {'format': 'gif'},
        {'format': 'PDF'},
        {'token': ''},
        {'token': 'not a jwt; Path=/'},
        {'token': 'a' * 8193},
        {'viewport': {'width': 100, 'height': 1024}},
        {'viewport': {'width': 1280, 'height': 99999}},
        {'viewport': {'width': '1280', 'height': 1024}},
        {'viewport': {'width': True, 'height': 1024}},
        {'full_page': 'yes'},
        {'pdf': {'page_size': 'A0', 'landscape': False}},
        {'pdf': {'page_size': 'A4', 'landscape': 'no'}},
        {'timeout_seconds': 0},
        {'timeout_seconds': -5},
        {'timeout_seconds': 'soon'},
        {'cookie': 'accessKey=planted'},
        {'wait_for': 'body'},
    ],
)
def test_malformed_or_unknown_fields_are_rejected(overrides):
    with pytest.raises(InvalidRenderRequest):
        parse(overrides)


@pytest.mark.parametrize('field', ['url', 'token', 'format'])
def test_required_fields_are_required(field):
    with pytest.raises(InvalidRenderRequest):
        parse(drop=(field,))


@pytest.mark.parametrize('body', [b'', b'not json', b'[]', b'"pdf"', b'\xff\xfe'])
def test_a_body_that_is_not_a_json_object_is_rejected(body):
    with pytest.raises(InvalidRenderRequest):
        parse_render_request(body, allowed_origin=ORIGIN, max_timeout_seconds=120)


def test_the_error_never_echoes_the_token():
    with pytest.raises(InvalidRenderRequest) as error:
        parse({'url': 'http://attacker.invalid/'})

    assert TOKEN not in str(error.value)
