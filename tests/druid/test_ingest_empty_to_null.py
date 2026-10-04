'''The ingest transform that stores the pipeline's `''` as null.

Its effect on query results is proven against live Druid by
scripts/druid/null_audit (WP-8a evidence); this pins its shape.
'''
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_PROBE = '''
import json
from datetime import datetime
from db.druid.indexing.common import build_data_schema
schema = build_data_schema('ds', datetime(2024, 1, 1), datetime(2024, 2, 1))
print(json.dumps(schema))
'''


def _data_schema() -> dict:
    # A subprocess keeps the dummy settings out of this test session's modules.
    env = {
        **os.environ,
        'PYTHONPATH': str(REPO_ROOT),
        'ZEN_HOME': str(REPO_ROOT),
        'R77_SRC_ROOT': str(REPO_ROOT),
        'ZEN_ENV': 'harmony_demo',
        'DRUID_HOST': 'http://druid.invalid',
        'DEFAULT_SECRET_KEY': 'test-only-not-a-secret',
    }
    result = subprocess.run(
        [sys.executable, '-c', _PROBE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_every_dimension_but_field_stores_empty_as_null():
    schema = _data_schema()
    dimensions = [
        d if isinstance(d, str) else d['name']
        for d in schema['dimensionsSpec']['dimensions']
    ]
    transforms = schema['transformSpec']['transforms']

    assert [t['name'] for t in transforms] == [d for d in dimensions if d != 'field']
    for transform in transforms:
        name = transform['name']
        assert transform == {
            'type': 'expression',
            'name': name,
            'expression': f'if("{name}" == \'\', null, "{name}")',
        }
