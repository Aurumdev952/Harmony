'''Peak RSS for 256 MiB of whitespace inside one element (about 250 KB gzip),
through GzipFile at the production read size.

    python f3_rss.py <path to json_stream.py>
'''

import gzip
import importlib.util
import io
import resource
import sys

spec = importlib.util.spec_from_file_location('json_stream_under_test', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

PATH = '/tmp/core3b/f3_padding.json.gz'  # noqa: S108 (scratch data)
if len(sys.argv) > 2 and sys.argv[2] == 'make':
    with open(PATH, 'wb') as f:
        f.write(
            gzip.compress(
                b'[[0], [1,' + b' ' * (256 * 1024 * 1024) + b'2]]', compresslevel=9
            )
        )
    sys.exit()
with open(PATH, 'rb') as f:
    wire = f.read()
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
rows, outcome = [], 'parsed'
try:
    for row in module.iter_json_array(gzip.GzipFile(fileobj=io.BytesIO(wire))):
        rows.append(row)
except ValueError as error:
    outcome = f'ValueError: {error}'
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
print(
    f'gzip {len(wire) / 1024:.0f} KiB; rows before the end {rows}; {outcome}; peak RSS growth {peak / 1024:.0f} MB'
)
