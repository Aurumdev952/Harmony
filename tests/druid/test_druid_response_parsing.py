'''Streamed Druid responses parse exactly, fast and row by row on CPython 3.13
(WP-3b, PERF-7).

Before WP-3b, streamed groupBy responses went through ijson-bigint's yajl C
backend, which reads Druid's Long.MIN_VALUE exactly. That backend does not build
on Python 3.11+, and ijson's pure-Python fallback is 8 to 16 times slower.
'''

import gzip
import itertools
import json
import math
import os
import time
import tracemalloc
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st
from requests.adapters import BaseAdapter
from requests.models import Response
from requests.structures import CaseInsensitiveDict

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-druid-placeholder-key')

# pylint: disable=wrong-import-position
from db.druid import json_stream
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
    '''Answers every POST with `wire`, the body as sent: gzip-encoded, as Druid
    sends it to a streamed request that accepts gzip, unless `gzipped` is False.'''

    def __init__(self, wire, gzipped):
        super().__init__()
        self.wire = wire
        self.gzipped = gzipped

    def send(self, request, stream=False, **kwargs):  # pylint: disable=arguments-differ
        assert stream and 'gzip' in request.headers['Accept-Encoding']
        headers = {'Content-Type': 'application/json'}
        if self.gzipped:
            headers['Content-Encoding'] = 'gzip'
        response = Response()
        response.status_code = 200
        response.headers = CaseInsensitiveDict(headers)
        response.raw = BytesIO(self.wire)
        response.request = request
        return response

    def close(self):
        pass


@contextmanager
def _client_answering(wire, gzipped=True):
    configuration = construct_druid_configuration('http://druid.parse.invalid')
    session = _get_session(configuration)
    prefix = configuration.query_endpoint()
    original = session.adapters[prefix]
    session.mount(prefix, _Broker(wire, gzipped))
    try:
        yield DruidQueryClient_(configuration)
    finally:
        session.mount(prefix, original)


def _stream(body, gzipped=True):
    wire = gzip.compress(body) if gzipped else body
    with _client_answering(wire, gzipped) as client:
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


def _best_of_3(run):
    best = float('inf')
    for _ in range(3):
        start = time.perf_counter()
        run()
        best = min(best, time.perf_counter() - start)
    return best


def test_large_response_parses_fast():
    # 100,000 array rows (13 MB). Timed against the stdlib's whole-body
    # json.loads of the same body in this process, so host load cancels out: the
    # client takes about 2 times as long, ijson's pure-Python backend (the 3.13
    # image's fallback) about 16 times.
    row = (
        '[1709510400000, "Município de São Paulo", "15-49", "Pará", 292.19, null,'
        ' 16, 1234.5678, 0.0, 48, "NaN", -9223372036854775808]'
    )
    body = ('[' + ','.join([row] * 100_000) + ']').encode()
    wire = gzip.compress(body)
    counts = []
    with _client_answering(wire) as client:
        client_seconds = _best_of_3(
            lambda: counts.append(
                sum(
                    1
                    for _ in client.run_raw_query(
                        {'queryType': 'groupBy'}, streaming=True
                    )
                )
            )
        )
    stdlib_seconds = _best_of_3(lambda: json.loads(gzip.decompress(wire)))
    assert counts == [100_000] * 3
    ratio = client_seconds / stdlib_seconds
    assert ratio < 6, f'{client_seconds:.2f} s, {ratio:.1f} times json.loads'


@pytest.mark.parametrize('gzipped', [True, False], ids=['gzip', 'identity'])
def test_identity_encoded_responses_parse_too(gzipped):
    body = b'[[1709510400000, "Acre", 1.5], [1709510400000, "Par\xc3\xa1", null]]'
    assert _stream(body, gzipped) == [
        [1709510400000, 'Acre', 1.5],
        [1709510400000, 'Pará', None],
    ]


def _peak_bytes_while_counting(wire):
    with _client_answering(wire) as client:
        tracemalloc.start()
        try:
            rows = client.run_raw_query({'queryType': 'groupBy'}, streaming=True)
            count = sum(1 for _ in rows)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    return count, peak


def test_rows_stream_without_holding_the_body():
    # 100,000 rows, 12 MB of JSON; decoding it whole holds over 60 MB.
    row = (
        '[1709510400000, "Município de São Paulo", "15-49", 292.19, null, 16,'
        ' 1234.5678, -9223372036854775808, "NaN", 0.0, 48, "Pará"]'
    ).encode()
    count, peak = _peak_bytes_while_counting(
        gzip.compress(b'[' + b','.join([row] * 100_000) + b']')
    )
    assert count == 100_000
    assert peak < 8 * 1024 * 1024, f'{peak / 2**20:.1f} MiB'


def test_highly_compressed_body_streams_without_inflating():
    # 64 MiB of JSON whitespace gzips to about 64 KB.
    wire = gzip.compress(b'[' + b' ' * (64 * 1024 * 1024) + b'[1]]', compresslevel=9)
    count, peak = _peak_bytes_while_counting(wire)
    assert count == 1
    assert peak < 8 * 1024 * 1024, f'{peak / 2**20:.1f} MiB'


_ROW = b'[1709510400000, "Acre", "Rio Branco", 150.0, 48]'


@pytest.mark.parametrize(
    'body',
    [
        # Security gate F3: whitespace inside one element must be buffered to
        # decode it, so a highly compressed body could fill memory.
        b'[[0], [1,' + b' ' * (64 * 1024 * 1024) + b'2]]',
        # Review (6): a malformed element is read on to the end of the body, as
        # the decoder cannot tell it from an incomplete one.
        b'[' + b','.join([_ROW] * 10 + [b'{"a":x}'] + [_ROW] * 400_000) + b']',
    ],
    ids=['padding-inside-an-element', 'malformed-element-early-in-a-large-body'],
)
def test_one_element_stops_at_the_element_cap(monkeypatch, body):
    # Against a 1 MiB cap.
    monkeypatch.setattr(json_stream, '_MAX_ELEMENT_CHARS', 1024 * 1024)
    wire = gzip.compress(body, compresslevel=9)
    rows = []
    with _client_answering(wire) as client:
        tracemalloc.start()
        try:
            with pytest.raises(ValueError, match='larger than'):
                rows = list(
                    client.run_raw_query({'queryType': 'groupBy'}, streaming=True)
                )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    # Fail closed: the caller gets an error, not the rows before it.
    assert rows == []
    assert peak < 16 * 1024 * 1024, f'{peak / 2**20:.1f} MiB'


def test_element_at_the_cap_parses(monkeypatch):
    element = b'["' + b'x' * 100 + b'"]'
    monkeypatch.setattr(json_stream, '_MAX_ELEMENT_CHARS', len(element))
    parsed = list(json_stream.iter_json_array(_Trickle(b'[' + element + b']', 7)))
    assert parsed == [['x' * 100]]


class _Trickle:
    '''A binary file that returns at most `size` bytes per read.'''

    def __init__(self, data, size):
        self.data = BytesIO(data)
        self.size = size

    def read(self, size=-1):
        return self.data.read(self.size if size < 0 else min(size, self.size))


def _golden_bodies():
    for path in sorted(GOLDEN_CASES.glob('*/druid_response.json')):
        for response in json.loads(path.read_text('utf-8')):
            yield json.dumps(response, ensure_ascii=False).encode()


@pytest.mark.parametrize('size', [1, 2, 3, 5, 7])
def test_every_read_boundary_parses_the_same(monkeypatch, size):
    # Small reads split numbers, escapes and multi-byte UTF-8 characters.
    monkeypatch.setattr(json_stream, '_READ_BYTES', 1)
    for body in [EDGE_BODY, *_golden_bodies()]:
        parsed = list(json_stream.iter_json_array(_Trickle(body, size)))
        assert _typed(parsed) == _typed(json.loads(body))


@pytest.mark.parametrize(
    'body, rows',
    [(b'[]', []), (b' \n[ ]\r\n', []), (b'\t[ 1 ,\n[2] ]\n', [1, [2]])],
    ids=['empty', 'empty-spaced', 'spaced'],
)
def test_array_framing(body, rows):
    assert list(json_stream.iter_json_array(BytesIO(body))) == rows


@pytest.mark.parametrize(
    'body',
    [
        b'[0.0]',
        b'[1.5e+300, -2E-5, 7]',
        b'[0.5e10]',
        b'[3, 0.25]',
        b'[1e5]',
        b'[-1E+2]',
        b'[12.25,3]',
    ],
    ids=[
        'fraction',
        'exponents',
        'fraction-exponent',
        'last',
        'exponent',
        'signed-exponent',
        'no-space',
    ],
)
def test_top_level_numbers_split_by_one_byte_reads(body):
    # A read that ends after "0" of "0.0" leaves a valid number "0" that is not
    # the whole number.
    parsed = list(json_stream.iter_json_array(_Trickle(body, 1)))
    assert _typed(parsed) == _typed(json.loads(body))


def test_top_level_number_split_at_the_production_read_size():
    # QA's repro: through GzipFile, the first 1 MiB read ends just after "0."
    body = b'[' + b' ' * (json_stream._READ_BYTES - 3) + b'0.5]'
    fp = gzip.GzipFile(fileobj=BytesIO(gzip.compress(body)))
    assert list(json_stream.iter_json_array(fp)) == [0.5]


class _Chunked:
    '''A binary file that returns successive reads of the given sizes, cycling.'''

    def __init__(self, data, sizes):
        self.data = BytesIO(data)
        self.sizes = itertools.cycle(sizes)

    def read(self, size=-1):
        chunk = next(self.sizes)
        return self.data.read(chunk if size < 0 else min(size, chunk))


_JSON_VALUES = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**63), max_value=2**63 - 1)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda inner: (
        st.lists(inner, max_size=4)
        | st.dictionaries(st.text(max_size=5), inner, max_size=4)
    ),
    max_leaves=12,
)


@given(
    rows=st.lists(_JSON_VALUES, max_size=8),
    sizes=st.lists(st.integers(min_value=1, max_value=9), min_size=1, max_size=6),
    ensure_ascii=st.booleans(),
    indent=st.sampled_from([None, 0, 2]),
)
@hypothesis_settings(max_examples=300, deadline=None)
def test_any_array_round_trips_in_any_chunking(rows, sizes, ensure_ascii, indent):
    body = json.dumps(rows, ensure_ascii=ensure_ascii, indent=indent).encode()
    parsed = list(json_stream.iter_json_array(_Chunked(body, sizes)))
    assert _typed(parsed) == _typed(json.loads(body))


@pytest.mark.parametrize(
    'body',
    [b'{"error": "x"}', b'', b'[1] 2', b'[1,]', b'[1 2]', b'[1'],
    ids=[
        'object',
        'empty-body',
        'trailing-data',
        'trailing-comma',
        'missing-comma',
        'unterminated',
    ],
)
def test_anything_but_one_array_fails(body):
    with pytest.raises(ValueError):
        list(json_stream.iter_json_array(BytesIO(body)))
