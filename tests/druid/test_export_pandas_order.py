'''Row order of the query frame on pandas 2 (WP-3b, INV-2).

pandas 2.2 sorts every outer merge by its keys, even with `sort=False`, which
reordered rows in 12 golden cases through date filling in `export_pandas`. The
expected values are what the pre-WP-3b code returned on pandas 1.5.3.
'''

import math
import os
import warnings

import pandas as pd
import pytest
from pydruid.query import Query

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-druid-placeholder-key')

# pylint: disable=wrong-import-position
from db.druid.query_builder import (
    PydruidQueryWrapper,
    outer_merge_in_appearance_order,
)


def _rows(df):
    return [
        [None if isinstance(v, float) and math.isnan(v) else v for v in row]
        for row in df.astype(object).values.tolist()
    ]


def test_outer_merge_keeps_pandas_1_order():
    # Duplicate and null keys, and keys found only on the right.
    left = pd.DataFrame(
        {
            'region': ['b', 'a', 'b', None, 'b'],
            'timestamp': ['t2', 't1', 't1', 't1', 't2'],
            'val': [1, 2, 3, 4, 5],
        }
    )
    right = pd.DataFrame(
        [(r, t) for r in ['b', 'a', None, 'c'] for t in ['t1', 't2', 't3']],
        columns=['region', 'timestamp'],
    )

    merged = outer_merge_in_appearance_order(left, right)

    assert list(merged.columns) == ['region', 'timestamp', 'val']
    assert list(merged.index) == list(range(13))
    assert _rows(merged) == [
        ['b', 't2', 1.0],
        ['b', 't2', 5.0],
        ['a', 't1', 2.0],
        ['b', 't1', 3.0],
        [None, 't1', 4.0],
        ['b', 't3', None],
        ['a', 't2', None],
        ['a', 't3', None],
        [None, 't2', None],
        [None, 't3', None],
        ['c', 't1', None],
        ['c', 't2', None],
        ['c', 't3', None],
    ]


def test_filled_dates_follow_the_returned_rows():
    query = PydruidQueryWrapper(
        Query({'granularity': 'month', 'dimensions': ['StateName']}, 'groupBy')
    )
    query.result = [
        {'event': {'timestamp': timestamp, 'StateName': state, 'cases': cases}}
        for timestamp, state, cases in [
            ('2024-01-01T00:00:00.000Z', 'Pará', 1.0),
            ('2024-01-01T00:00:00.000Z', 'Acre', 2.0),
            ('2024-02-01T00:00:00.000Z', 'Pará', 3.0),
            ('2024-03-01T00:00:00.000Z', 'Acre', 4.0),
        ]
    ]

    filled = query.export_pandas(fill_intermediate_dates=True)

    assert list(filled.columns) == ['timestamp', 'StateName', 'cases']
    assert list(filled.index) == list(range(6))
    assert _rows(filled) == [
        ['2024-01-01T00:00:00.000Z', 'Pará', 1.0],
        ['2024-01-01T00:00:00.000Z', 'Acre', 2.0],
        ['2024-02-01T00:00:00.000Z', 'Pará', 3.0],
        ['2024-03-01T00:00:00.000Z', 'Acre', 4.0],
        ['2024-03-01T00:00:00.000Z', 'Pará', None],
        ['2024-02-01T00:00:00.000Z', 'Acre', None],
    ]


@pytest.mark.parametrize(
    'granularity, last, expected',
    [
        ('day', '2024-01-03', ['2024-01-01', '2024-01-02', '2024-01-03']),
        ('week', '2024-01-15', ['2024-01-01', '2024-01-08', '2024-01-15']),
        ('month', '2024-03-01', ['2024-01-01', '2024-02-01', '2024-03-01']),
        ('quarter', '2024-07-01', ['2024-01-01', '2024-04-01', '2024-07-01']),
    ],
)
def test_result_dates_use_current_pandas_aliases(granularity, last, expected):
    # pandas 2.2 deprecates the lower-case period aliases 'w', 'm' and 'q'.
    query = PydruidQueryWrapper(
        Query({'granularity': granularity, 'dimensions': []}, 'groupBy')
    )
    df = pd.DataFrame(
        {'timestamp': ['2024-01-01T00:00:00.000Z', f'{last}T00:00:00.000Z']}
    )

    with warnings.catch_warnings():
        warnings.simplefilter('error', FutureWarning)
        dates = query._build_result_dates(df)  # pylint: disable=protected-access

    assert dates == [f'{day}T00:00:00.000Z' for day in expected]
