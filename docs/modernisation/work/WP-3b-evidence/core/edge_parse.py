'''Parse edge-value documents with each available parser and print value+type.

python edge_parse.py <variant> [<variant> ...]
'''

import io
import json
import math
import sys

DOCS = {
    'ints': b'[[-9223372036854775808, 9223372036854775807, 0, -0, 1, -1, 4294967296]]',
    'u64': b'[[18446744073709551615]]',
    'beyond_u64': b'[[18446744073709551616, -9223372036854775809]]',
    'floats': (
        b'[[0.1, -0.0, 1.5, 123456789.123456789, 1E5, 1e-7, 2.5e+10, 1.0,'
        b' 1.7976931348623157e308, 5e-324, 2.2250738585072014e-308,'
        b' 9007199254740993.0, 0.30000000000000004]]'
    ),
    'float_overflow': b'[[1e309]]',
    'quoted_special': b'[["NaN", "Infinity", "-Infinity", null, true, false]]',
    'bare_nan': b'[[NaN]]',
    'bare_infinity': b'[[Infinity, -Infinity]]',
    'non_ascii': (
        '[["São Paulo", "Pará", "日本", "\U0001f600",'
        ' "\\u00e3", "\\ud83d\\ude00", "tab\\tq\\"b\\\\", "\\/"]]'
    ).encode(),
    'lone_surrogate': b'[["\\ud800"]]',
    'invalid_utf8': b'[["\xff\xfe"]]',
    'nested': b'[[1, [0.5, 0.9], {"a": [1, {"b": null}]}], {"timestamp": "x", "result": {"v": 1}}]',
    'empty': b'[]',
}


def parser(variant):
    if variant == 'client':
        # The WP-3b client's decoder; run from the repository root.
        sys.path.insert(0, '.')
        from db.druid.json_stream import iter_json_array

        return lambda data: list(iter_json_array(io.BytesIO(data)))
    if variant.startswith('ijson'):
        import ijson

        backend = ijson.get_backend(variant.split('_', 1)[1])
        return lambda data: list(
            backend.items(io.BytesIO(data), 'item', use_float=True)
        )
    if variant == 'json':
        return json.loads
    if variant == 'orjson':
        import orjson

        return orjson.loads
    if variant == 'msgspec':
        import msgspec

        return msgspec.json.Decoder().decode
    raise SystemExit(variant)


def show(value):
    if isinstance(value, list):
        return '[' + ', '.join(show(v) for v in value) + ']'
    if isinstance(value, dict):
        return '{' + ', '.join(f'{k!r}: {show(v)}' for k, v in value.items()) + '}'
    if isinstance(value, float):
        return f'float({value!r}{" neg" if math.copysign(1, value) < 0 else ""})'
    return f'{type(value).__name__}({value!r})'


for variant in sys.argv[1:]:
    parse = parser(variant)
    for name, data in DOCS.items():
        try:
            result = show(parse(data))
        except Exception as error:  # noqa: BLE001
            result = f'ERROR {type(error).__name__}'
        print(f'{name}\t{variant}\t{result}')
