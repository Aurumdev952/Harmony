"""ijson-bigint backends in this environment: Druid's Long.MIN_VALUE and speed."""

import io
import time

import ijson

print("default backend", ijson.backend)
doc = b'[{"a": -9223372036854775808, "b": 9223372036854775807, "d": 1.5, "e": null}]'
row = b'{"timestamp": "2024-01-01T00:00:00.000Z", "event": {"region": "North", "val": 1234.5, "cnt": 42}}'
big = b"[" + b",".join([row] * 200_000) + b"]"
for name in ["yajl2_c", "yajl2_cffi", "yajl2", "python"]:
    try:
        backend = ijson.get_backend(name)
    except Exception as e:  # noqa: BLE001
        print(name, "unavailable:", type(e).__name__)
        continue
    try:
        print(name, list(backend.items(io.BytesIO(doc), "item", use_float=True)))
    except Exception as e:  # noqa: BLE001
        print(name, "ERROR", type(e).__name__, str(e).splitlines()[0])
    t = time.perf_counter()
    n = sum(1 for _ in backend.items(io.BytesIO(big), "item", use_float=True))
    print(
        f"  {name}: {n} rows, {len(big) / 1e6:.1f} MB in {time.perf_counter() - t:.2f}s"
    )
