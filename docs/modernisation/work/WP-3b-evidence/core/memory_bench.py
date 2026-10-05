'''Peak memory of one streamed Druid response through the production client.

    python memory_bench.py <tree> <body.json or body.json.gz> <stream|retain>

The broker adapter serves the body gzip-encoded, as Druid does. `stream` drops
each row once read; `retain` keeps every row (export_pandas ends up holding all of
them in its frame). Prints the peak RSS growth over the baseline taken after the
imports and the gzip body are in memory.
'''

import gzip
import json
import os
import resource
import sys
import time
from io import BytesIO

root = os.path.abspath(sys.argv[1])
sys.path.insert(0, root)
os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'memory-bench')

from requests.adapters import BaseAdapter  # noqa: E402
from requests.models import Response  # noqa: E402
from requests.structures import CaseInsensitiveDict  # noqa: E402

from db.druid.config import construct_druid_configuration  # noqa: E402
from db.druid.query_client import DruidQueryClient_, _get_session  # noqa: E402

path, mode = sys.argv[2], sys.argv[3]
if path.endswith('.gz'):
    with open(path, 'rb') as f:
        wire = f.read()
    body_size = None
else:
    # A golden file holds every response of a case; serve the largest one.
    responses = json.load(open(path, encoding='utf-8'))
    body = max((json.dumps(r).encode() for r in responses), key=len)
    body_size = len(body)
    wire = gzip.compress(body)
    del responses, body


class Broker(BaseAdapter):
    def send(self, request, stream=False, **kwargs):  # pylint: disable=arguments-differ
        response = Response()
        response.status_code = 200
        response.headers = CaseInsensitiveDict(
            {'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}
        )
        response.raw = BytesIO(wire)
        response.request = request
        return response

    def close(self):
        pass


configuration = construct_druid_configuration('http://druid.memory.invalid')
_get_session(configuration).mount(configuration.query_endpoint(), Broker())
client = DruidQueryClient_(configuration)

baseline = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
start = time.perf_counter()
result = client.run_raw_query({'queryType': 'groupBy'}, streaming=True)
if mode == 'retain':
    rows = list(result)
    count = len(rows)
else:
    count = sum(1 for _ in result)
elapsed = time.perf_counter() - start
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - baseline
print(
    f'{os.path.basename(path)}\t{mode}\trows={count}\t'
    f'body={(body_size or 0) / 1e6:.3f}MB\tpeak_growth={peak / 1024:.1f}MB\t'
    f'time={elapsed:.2f}s\tpy={sys.version.split()[0]}'
)
