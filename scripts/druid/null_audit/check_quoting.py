'''Show that Druid parses the ingest transform's escaped dimension names.

    PYTHONPATH=. uv run python scripts/druid/null_audit/check_quoting.py --port 58891

Indexes two rows into `wp8a_quoting`, with a dimension whose name holds a quote
and a backslash, through `build_empty_to_null_transforms`. Exits non-zero unless
the `''` row comes back null and the other keeps its value: the expression
parsed, and it read the column it names.
'''

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# pylint: disable=wrong-import-position
from scripts.druid.null_audit.run_audit import _router, _run_index_task
from tests.golden.harness import bootstrap

DATASOURCE = 'wp8a_quoting'
NAME = 'a"b\\c'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    bootstrap()
    # pylint: disable=import-outside-toplevel
    from db.druid.indexing.common import build_empty_to_null_transforms

    rows = [
        {'date': '2024-01-01', NAME: '', 'plain': 'x'},
        {'date': '2024-01-02', NAME: 'kept', 'plain': ''},
    ]
    task = {
        'type': 'index_parallel',
        'spec': {
            'dataSchema': {
                'dataSource': DATASOURCE,
                'timestampSpec': {'column': 'date', 'format': 'yyyy-MM-dd'},
                'dimensionsSpec': {'dimensions': [NAME, 'plain']},
                'transformSpec': {
                    'transforms': build_empty_to_null_transforms([NAME, 'plain'])
                },
                'granularitySpec': {
                    'segmentGranularity': 'MONTH',
                    'queryGranularity': 'none',
                    'rollup': False,
                },
            },
            'ioConfig': {
                'type': 'index_parallel',
                'inputSource': {
                    'type': 'inline',
                    'data': '\n'.join(json.dumps(row) for row in rows),
                },
                'inputFormat': {'type': 'json'},
            },
            'tuningConfig': {'type': 'index_parallel'},
        },
    }
    base = _router(args.port)
    _run_index_task(base, DATASOURCE, task)
    response = requests.post(
        f'{base}/druid/v2',
        json={
            'queryType': 'scan',
            'dataSource': DATASOURCE,
            'intervals': ['2024-01-01/2024-02-01'],
            'columns': [NAME, 'plain'],
            'resultFormat': 'compactedList',
            'order': 'none',
        },
        timeout=60,
    )
    response.raise_for_status()
    got = sorted(
        (tuple(event) for batch in response.json() for event in batch['events']),
        key=repr,
    )
    expected = sorted([(None, 'x'), ('kept', None)], key=repr)
    print(f'{NAME!r} and plain after the transform: {got}')
    return 0 if got == expected else 1


if __name__ == '__main__':
    sys.exit(main())
