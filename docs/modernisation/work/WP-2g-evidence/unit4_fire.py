'''Fire 40 concurrent requests and check every access line against the app line
and the response header that share its request id.'''

import collections
import concurrent.futures
import json
import sys
import time
import urllib.request

base, log_path = sys.argv[1], sys.argv[2]


def call(n):
    headers = {'X-Request-ID': f'client-{n}'} if n % 2 == 0 else {}
    if n % 5 == 0:
        headers = {'X-Request-ID': 'bad id with spaces'}
    # base is the local gunicorn URL that unit4_run_live.sh passes.
    url = f'{base}/work/{n}?token=sekrit{n}'
    req = urllib.request.Request(url, headers=headers)  # noqa: S310
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        return n, resp.headers['X-Request-ID']


with concurrent.futures.ThreadPoolExecutor(20) as pool:
    responses = dict(pool.map(call, range(40)))


time.sleep(1)
entries = [json.loads(line) for line in open(log_path) if line.startswith('{')]
access = {}
views = {}
for entry in entries:
    if entry['logger'] == 'gunicorn.access':
        n = int(entry['http']['path'].rsplit('/', 1)[1])
        access[n] = entry
    elif entry['logger'] == 'wp2g.view':
        views[int(entry['message'].rsplit(' ', 1)[1])] = entry

problems = []
for n, header_id in responses.items():
    if n % 5 == 0:
        expected_from_client = None
    elif n % 2 == 0:
        expected_from_client = f'client-{n}'
    else:
        expected_from_client = None
    if expected_from_client and header_id != expected_from_client:
        problems.append((n, 'header', header_id))
    if access[n].get('request_id') != header_id:
        problems.append((n, 'access', access[n].get('request_id'), header_id))
    if views[n].get('request_id') != header_id:
        problems.append((n, 'view', views[n].get('request_id'), header_id))
ids = [access[n]['request_id'] for n in responses]
duplicates = [i for i, c in collections.Counter(ids).items() if c > 1]
raw = open(log_path).read()
print('responses', len(responses), 'access', len(access), 'views', len(views))
print('distinct request ids', len(set(ids)), 'duplicates', duplicates)
print('non-json lines', sum(1 for line in raw.splitlines() if not line.startswith('{')))
print('query token leaked', 'sekrit' in raw)
print('rejected client id echoed', 'bad id with spaces' in raw)
print('problems', problems)
sys.exit(1 if problems or duplicates or 'sekrit' in raw else 0)
