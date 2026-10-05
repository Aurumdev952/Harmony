'''End-to-end: POST /api2/query/table for table_disaggregated with its recorded
Druid response scaled to ~ROWS rows (municipality names suffixed per copy), through
the production client (gzip stream + parser), parse, export_pandas and shaping.

    python e2e_bench.py <tree> [rows]
'''

import gc
import gzip
import json
import os
import resource
import sys
import time

root = os.path.abspath(sys.argv[1])
os.chdir(root)
sys.path.insert(0, root)
target = int(sys.argv[2]) if len(sys.argv) > 2 else 200_000

from tests.golden.harness import bootstrap  # noqa: E402

bootstrap()
from tests.golden.harness import load_cases, run_case  # noqa: E402

import db.druid.query_client as qc  # noqa: E402

case = next(c for c in load_cases() if c.name == 'table_disaggregated')
recorded = case.read('druid_response.json')[0]
copies = target // len(recorded) + 1
rows = [
    [r[0], r[1], r[2], f'{r[3]} {k}', r[4], r[5]]
    for k in range(copies)
    for r in recorded
][:target]

start = time.perf_counter()
body = gzip.compress(json.dumps(rows).encode())
serialise = time.perf_counter() - start
if os.environ.get('FORCE_IJSON'):
    import ijson

    qc.ijson = ijson.get_backend(os.environ['FORCE_IJSON'])
parser = getattr(qc, 'ijson', None)
backend = getattr(parser, 'backend', 'n/a') if parser else 'none (no ijson in client)'

gc.collect()
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
times = []
for _ in range(3):
    start = time.perf_counter()
    _, response = run_case(case, lambda query: rows)
    times.append(time.perf_counter() - start)
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
print(
    f'rows={len(rows)} body={len(body) / 1e6:.1f}MB gz, '
    f'best={min(times):.2f}s (broker dumps+gzip {serialise:.2f}s), '
    f'peak RSS growth={peak / 1024:.0f}MB, out rows={len(response["data"])}, '
    f'py={sys.version.split()[0]} ijson backend={backend}'
)
