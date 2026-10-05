'''Time and measure peak memory of Druid response parsers over a gzip body.

    python parse_bench.py make            # writes /tmp/core3b/bench_{array,dict}.json.gz
    python parse_bench.py run <variant> <shape>

Each `run` is one process: it gunzips the body as the client does (GzipFile over
a file object), parses every row, and reports the best of 5 wall times and the
process's peak RSS growth over the run.
'''

import gzip
import io
import json
import random
import resource
import sys
import time

ROWS = 200_000
STATES = ['Acre', 'Pará', 'Roraima', 'São Paulo', 'Maranhão', 'Ceará', 'Piauí']
MUNIS = [f'Município {i} — Zona {i % 7}' for i in range(3000)]


def make():
    rng = random.Random(3)  # noqa: S311 (reproducible benchmark data)
    rows = []
    for i in range(ROWS):
        ts = 1514764800000 + (i % 96) * 2678400000
        vals = []
        for _ in range(6):
            r = rng.random()
            vals.append(
                None
                if r < 0.15
                else (
                    'NaN'
                    if r < 0.16
                    else ('Infinity' if r < 0.165 else rng.uniform(-1e6, 1e9))
                )
            )
        counts = [rng.randint(0, 5000) for _ in range(3)]
        if i % 50_000 == 0:
            counts[0] = -9223372036854775808
            counts[1] = 9223372036854775807
        rows.append(
            [
                ts,
                rng.choice(STATES),
                rng.choice(MUNIS),
                rng.choice(['M', 'F', None]),
                *vals,
                *counts,
            ]
        )
    with gzip.open('/tmp/core3b/bench_array.json.gz', 'wb') as f:  # noqa: S108 (scratch data)
        f.write(json.dumps(rows, ensure_ascii=False).encode())
    row = b'{"timestamp": "2024-01-01T00:00:00.000Z", "event": {"region": "North", "val": 1234.5, "cnt": 42}}'
    with gzip.open('/tmp/core3b/bench_dict.json.gz', 'wb') as f:  # noqa: S108 (scratch data)
        f.write(b'[' + b','.join([row] * ROWS) + b']')


def parser(variant):
    if variant.startswith('ijson'):
        import ijson

        backend = ijson.get_backend(variant.split('_', 1)[1])
        return lambda fp: backend.items(fp, 'item', use_float=True)
    if variant == 'client':
        # The WP-3b client's decoder; run from the repository root.
        sys.path.insert(0, '.')
        from db.druid.json_stream import iter_json_array

        return iter_json_array
    if variant == 'json':
        return lambda fp: json.load(fp)
    if variant == 'orjson':
        import orjson

        return lambda fp: orjson.loads(fp.read())
    if variant == 'msgspec':
        import msgspec

        decode = msgspec.json.Decoder().decode
        return lambda fp: decode(fp.read())
    raise SystemExit(variant)


def run(variant, shape):
    with open(f'/tmp/core3b/bench_{shape}.json.gz', 'rb') as f:  # noqa: S108 (scratch data)
        compressed = f.read()
    parse = parser(variant)
    base_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    best = float('inf')
    for _ in range(5):
        start = time.perf_counter()
        n = 0
        for _row in parse(gzip.GzipFile(fileobj=io.BytesIO(compressed))):
            n += 1
        best = min(best, time.perf_counter() - start)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - base_rss
    print(
        f'{variant}\t{shape}\t{n}\t{best:.3f}\t{peak / 1024:.0f}\t{sys.version.split()[0]}'
    )


if sys.argv[1] == 'make':
    make()
else:
    run(sys.argv[2], sys.argv[3])
