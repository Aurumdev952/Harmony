'''Time requests with hostile paths against the unit 4 gunicorn app (gevent, two
workers, the WP-2g log config), the way the reviewer found the quadratic
redaction: each access line passes the path through the redaction patterns.

    unit4_run_live.sh starts the server; this takes its base URL:
    python rework_hostile_paths.py http://127.0.0.1:18743

Prints the slowest of five requests per path. gunicorn's request line limit is
4094 bytes, so the paths stay under it.
'''

import sys
import time
import urllib.error
import urllib.request

base = sys.argv[1]
PATHS = {
    'a-a-a (4071 bytes)': '/' + 'a-' * 2035,
    'token-token- (4069 bytes)': '/' + 'token-' * 678,
    'slashes (4070 bytes)': '/' * 4070,
    'ordinary': '/work/1',
}

for label, path in PATHS.items():
    slowest = 0.0
    for _ in range(5):
        start = time.perf_counter()
        try:
            # base is the local gunicorn URL the caller passes.
            with urllib.request.urlopen(base + path) as response:  # noqa: S310
                response.read()
        except urllib.error.HTTPError as error:
            error.read()
        slowest = max(slowest, time.perf_counter() - start)
    print(f'{label}: slowest of 5 requests {slowest:.3f}s')
