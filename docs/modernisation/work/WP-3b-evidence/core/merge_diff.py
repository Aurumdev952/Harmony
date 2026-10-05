'''Write, for 500 random frame pairs, the outer merge result (rows, dtypes, index).
On pandas 1.x use merge(how='outer', sort=False); otherwise the helper.

    python merge_diff.py <tree> <out.json>
'''

import json
import os
import random
import sys

root = os.path.abspath(sys.argv[1])
sys.path.insert(0, root)
os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'x')

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

if pd.__version__.startswith('1.'):

    def merge(left, right):
        return left.merge(right, how='outer', sort=False, copy=False)
else:
    from db.druid.query_builder import outer_merge_in_appearance_order as merge  # noqa: E402

rng = random.Random(7)  # noqa: S311 (reproducible benchmark data)
out = []
for case in range(500):
    n_left, n_right = rng.randint(0, 12), rng.randint(0, 12)
    regions = ['a', 'b', 'c', None]
    stamps = ['t1', 't2', 't3']

    def key():
        return rng.choice(regions), rng.choice(stamps)

    left_keys = [key() for _ in range(n_left)]
    right_keys = [key() for _ in range(n_right)]
    left = pd.DataFrame(left_keys, columns=['region', 'timestamp'])
    left['val'] = [rng.random() for _ in range(n_left)]
    left['count'] = np.arange(n_left, dtype='int64')
    left['flag'] = [rng.random() < 0.5 for _ in range(n_left)]
    right = pd.DataFrame(right_keys, columns=['region', 'timestamp'])
    if case % 2:
        right['extra'] = np.arange(n_right, dtype='int64')
    if n_left == 0 or n_right == 0:
        # export_pandas never merges an empty frame; pandas 1.x had a separate
        # path for that, which the helper does not copy.
        continue
    merged = merge(left, right)
    rows = [
        [
            None
            if (isinstance(v, float) and np.isnan(v)) or v is None
            else (v.item() if hasattr(v, 'item') else v)
            for v in row
        ]
        for row in merged.astype(object).values.tolist()
    ]
    out.append(
        {
            'columns': list(merged.columns),
            'dtypes': [str(d) for d in merged.dtypes],
            'index': list(map(int, merged.index)),
            'rows': rows,
        }
    )
with open(sys.argv[2], 'w') as f:
    json.dump(out, f, indent=0, default=str)
print(pd.__version__, len(out))
