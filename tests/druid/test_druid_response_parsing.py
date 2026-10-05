'''Streamed Druid responses parse exactly and fast on CPython 3.13 (WP-3b, PERF-7).

Before WP-3b, streamed groupBy responses went through ijson-bigint's yajl C
backend, which reads Druid's Long.MIN_VALUE exactly. That backend does not build
on Python 3.11+, and ijson's pure-Python fallback is 8 to 16 times slower.
'''

import gzip
import json
import math
import os
import time
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import pytest
from requests.adapters import BaseAdapter
from requests.models import Response
from requests.structures import CaseInsensitiveDict

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-druid-placeholder-key')

# pylint: disable=wrong-import-position
from db.druid.config import construct_druid_configuration
from db.druid.query_client import DruidQueryClient_, _get_session

GOLDEN_CASES = Path(__file__).resolve().parents[1] / 'golden' / 'cases'

# Druid (Jackson) writes longs in full, doubles in Java's shortest form with an
# upper-case exponent, NaN and the infinities as strings, and non-ASCII as UTF-8.
EDGE_BODY = (
    '[[1709510400000, "São Paulo", "日本 😀", "\\u00e3\\ud83d\\ude00", null,'
    ' -9223372036854775808, 9223372036854775807, 0, -1,'
    ' 1.7976931348623157E308, 4.9E-324, 2.2250738585072014E-308, -0.0, 0.1,'
    ' 1.2345678912345679E8, 9.007199254740992E15, 1.0E-7,'
    ' "NaN", "Infinity", "-Infinity", [0.5, 0.9], {"a": [1, null]}]]'
).encode()
EDGE_ROW = [
    1709510400000,
    'São Paulo',
    '日本 😀',
    'ã😀',
    None,
    -9223372036854775808,
    9223372036854775807,
    0,
    -1,
    1.7976931348623157e308,
    5e-324,
    2.2250738585072014e-308,
    -0.0,
    0.1,
    123456789.12345679,
    9007199254740992.0,
    1e-07,
    'NaN',
    'Infinity',
    '-Infinity',
    [0.5, 0.9],
    {'a': [1, None]},
]


class _Broker(BaseAdapter):
    '''Answers every POST with `body`, gzip-encoded as Druid does for a streamed
    request that accepts gzip.'''

    def __init__(self, body):
        super().__init__()
        self.body = body

    def send(self, request, stream=False, **kwargs):  # pylint: disable=arguments-differ
        assert stream and 'gzip' in request.headers['Accept-Encoding']
        response = Response()
        response.status_code = 200
        response.headers = CaseInsensitiveDict(
            {'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}
        )
        response.raw = BytesIO(gzip.compress(self.body))
        response.request = request
        return response

    def close(self):
        pass


@contextmanager
def _client_answering(body):
    configuration = construct_druid_configuration('http://druid.parse.invalid')
    session = _get_session(configuration)
    prefix = configuration.query_endpoint()
    original = session.adapters[prefix]
    session.mount(prefix, _Broker(body))
    try:
        yield DruidQueryClient_(configuration)
    finally:
        session.mount(prefix, original)


def _stream(body):
    with _client_answering(body) as client:
        return list(client.run_raw_query({'queryType': 'groupBy'}, streaming=True))


def _typed(value):
    '''`value` with each scalar tagged by its type, so 1 differs from 1.0 and 0.0
    from -0.0.'''
    if isinstance(value, list):
        return [_typed(v) for v in value]
    if isinstance(value, dict):
        return {k: _typed(v) for k, v in value.items()}
    if isinstance(value, float):
        return ('float', repr(value), math.copysign(1.0, value))
    return (type(value).__name__, value)


def _golden_responses():
    for path in sorted(GOLDEN_CASES.glob('*/druid_response.json')):
        for index, response in enumerate(json.loads(path.read_text('utf-8'))):
            yield pytest.param(response, id=f'{path.parent.name}[{index}]')


@pytest.mark.parametrize('response', _golden_responses())
@pytest.mark.parametrize('ensure_ascii', [True, False], ids=['ascii', 'utf8'])
def test_golden_responses_round_trip(response, ensure_ascii):
    body = json.dumps(response, ensure_ascii=ensure_ascii).encode()
    assert _typed(_stream(body)) == _typed(json.loads(body))


def test_druid_edge_values_parse_exactly():
    assert _typed(_stream(EDGE_BODY)) == _typed([EDGE_ROW])


@pytest.mark.parametrize(
    'body',
    [b'[[NaN]]', b'[[Infinity]]', b'[[1e309]]', b'[[1, 2]', b'[["\xff"]]'],
    ids=['bare-nan', 'bare-infinity', 'double-overflow', 'truncated', 'bad-utf8'],
)
def test_bodies_yajl_rejected_still_fail(body):
    with pytest.raises(ValueError):
        _stream(body)


def test_large_response_parses_fast():
    # 100,000 array rows (13 MB). msgspec parses them in about 0.07 s; ijson's
    # pure-Python backend, which the 3.13 image would fall back to, in 1.2 s.
    row = (
        '[1709510400000, "Município de São Paulo", "15-49", "Pará", 292.19, null,'
        ' 16, 1234.5678, 0.0, 48, "NaN", -9223372036854775808]'
    )
    body = ('[' + ','.join([row] * 100_000) + ']').encode()
    start = time.perf_counter()
    rows = _stream(body)
    elapsed = time.perf_counter() - start
    assert len(rows) == 100_000
    assert elapsed < 0.5, f'{elapsed:.2f} s'
