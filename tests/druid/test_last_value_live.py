'''Native LAST_VALUE gives the extension's results on live Druid (WP-8a, N3).

LAST_VALUE aggregates, per result row, only the rows at the latest `__time`
among those its filter keeps; rows tied at that time all count. The reference
here uses core aggregators only: it groups by the exact `__time` as well, and
keeps the latest entry of each group client-side. The native query is what the
production builder posts (`GroupByQueryBuilder` with
`HARMONY_DRUID_LAST_VALUE=native`).

Runs only against Druids named in `LAST_VALUE_LIVE_PORTS` (router ports, comma
separated), loaded with the WP-8a audit dataset (`scripts/druid/null_audit`).
Ports in `LAST_VALUE_EXTENSION_PORTS` also run the `aggregateLast` extension
and must give the same rows, which works only on 0.23 with legacy nulls.

    LAST_VALUE_LIVE_PORTS=58891,58892,58893 LAST_VALUE_EXTENSION_PORTS=58891 \\
        uv run pytest tests/druid/test_last_value_live.py
'''

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from typing import Optional

import pytest
import requests

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'druid-tests-not-a-secret')
os.environ.setdefault('DRUID_HOST', 'http://druid.druid-tests.invalid')

# pylint: disable=wrong-import-position
from data.query.models.calculation.last_value_calculation import (
    AggregationOperation,
    LastValueCalculation,
)
from data.query.models.query_filter import FieldFilter
from db.druid.aggregations.last_value_aggregation import LAST_VALUE_SETTING
from db.druid.query_builder import GroupByQueryBuilder
from tests.golden.harness import _array_header

PORTS = [int(p) for p in os.environ.get('LAST_VALUE_LIVE_PORTS', '').split(',') if p]
EXTENSION_PORTS = {
    int(p) for p in os.environ.get('LAST_VALUE_EXTENSION_PORTS', '').split(',') if p
}
DATASOURCE = os.environ.get('LAST_VALUE_LIVE_DATASOURCE', 'harmony_demo_20260101')
FIELD = 'yellow_fever_cases'
RESULT = 'last'
TIMEOUT_S = 120

pytestmark = pytest.mark.skipif(not PORTS, reason='LAST_VALUE_LIVE_PORTS not set')

# (operation, metric, the core aggregator that combines rows at one time)
OPERATIONS = [
    (AggregationOperation.SUM, 'sum', 'doubleSum'),
    (AggregationOperation.COUNT, 'count', 'doubleSum'),
    (AggregationOperation.MAX, 'max', 'doubleMax'),
    (AggregationOperation.MIN, 'min', 'doubleMin'),
]
INTERVALS = ['2018-01-01/2026-01-01', '2024-01-01/2024-04-01']
GRANULARITIES = ['all', 'year', 'month', 'week', 'day']
GROUPINGS = [
    [],
    ['StateName'],
    ['StateName', 'MunicipalityName'],
    ['Sex'],
    ['source', 'Age'],
]

# (time bucket or None for granularity all, dimension values)
Key = tuple[Optional[int], tuple[Optional[str], ...]]


def _post(port: int, query: dict) -> list:
    response = requests.post(
        f'http://127.0.0.1:{port}/druid/v2', json=query, timeout=TIMEOUT_S
    )
    assert response.status_code == 200, response.text[:2000]
    return response.json()


def _builder_query(operation, granularity, grouping, interval) -> dict:
    calculation = LastValueCalculation(
        filter=FieldFilter(FIELD), operation=operation
    ).to_druid(RESULT)
    query = (
        GroupByQueryBuilder(
            datasource=DATASOURCE,
            granularity=granularity,
            grouping_fields=list(grouping),
            intervals=[interval],
            calculation=calculation,
        )
        .prepare()
        .query_dict
    )
    if query['queryType'] == 'timeseries':
        # Like groupBy, return only buckets that have rows, as the reference does.
        query['context'] = {**query.get('context', {}), 'skipEmptyBuckets': True}
    return query


def _dimension_names(query: dict) -> list[str]:
    return [
        d if isinstance(d, str) else d['outputName']
        for d in query.get('dimensions', [])
    ]


def _rows(query: dict, result: list) -> dict[Key, dict]:
    '''Result rows by (bucket, dimension values), from either query type.'''
    if query['queryType'] == 'timeseries':
        return {(_bucket(query, row['timestamp']), ()): row['result'] for row in result}
    header = _array_header(query)
    dimensions = _dimension_names(query)
    output = {}
    for values in result:
        row = dict(zip(header, values))
        key = (row.get('__timestamp'), tuple(row[d] for d in dimensions))
        assert key not in output
        output[key] = row
    return output


def _bucket(query: dict, timestamp: str) -> int | None:
    '''A row's time bucket in epoch milliseconds; None for granularity all,
    whose single bucket the array rows leave out.'''
    if query['granularity'] == 'all':
        return None
    parsed = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f%z')
    return int(parsed.timestamp() * 1000)


def _reference(port, query: dict, metric: str, combine: str) -> dict[Key, dict]:
    '''Per (bucket, dimension values): the latest row time, the value of the
    rows at that time, how many rows share it, and how many times there were.'''
    dimensions = _dimension_names(query)
    reference_query = {
        'queryType': 'groupBy',
        'dataSource': DATASOURCE,
        'intervals': query['intervals'],
        'granularity': query['granularity'],
        'filter': query['filter'],
        'dimensions': dimensions
        + [
            {
                'type': 'default',
                'dimension': '__time',
                'outputName': '__row_time',
                'outputType': 'LONG',
            }
        ],
        'aggregations': [
            {'type': combine, 'name': 'value', 'fieldName': metric},
            {'type': 'count', 'name': 'rows'},
        ],
    }
    latest: dict[Key, dict] = {}
    times: dict[Key, int] = defaultdict(int)
    for entry in _post(port, reference_query):
        event = entry['event']
        key = (
            _bucket(query, entry['timestamp']),
            tuple(event.get(d) for d in dimensions),
        )
        times[key] += 1
        if key not in latest or event['__row_time'] > latest[key]['__row_time']:
            latest[key] = event
    return {key: {**latest[key], 'times': times[key]} for key in latest}


def _shapes():
    for operation, metric, combine in OPERATIONS:
        for interval in INTERVALS:
            for granularity in GRANULARITIES:
                for grouping in GROUPINGS:
                    yield operation, metric, combine, interval, granularity, grouping


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setenv(LAST_VALUE_SETTING, 'native')


@pytest.mark.parametrize('port', PORTS)
def test_native_last_value_matches_the_reference(native, port):
    shapes = ties = latest_only = 0
    for operation, metric, combine, interval, granularity, grouping in _shapes():
        query = _builder_query(operation, granularity, grouping, interval)
        native_rows = _rows(query, _post(port, query))
        reference = _reference(port, query, metric, combine)
        label = f'{operation.value} {interval} {granularity} {grouping}'
        assert set(native_rows) == set(reference), label
        for key, expected in reference.items():
            assert native_rows[key][RESULT] == expected['value'], (label, key)
            ties += expected['rows'] > 1
            latest_only += expected['times'] > 1
        shapes += 1
    # The proof is not vacuous: rows tied at the latest time and earlier times
    # that must be ignored both occur.
    assert shapes == len(list(_shapes()))
    assert ties and latest_only, (ties, latest_only)


@pytest.mark.parametrize('port', PORTS)
def test_native_average_is_the_ratio_at_the_latest_time(native, port):
    for interval in INTERVALS:
        for granularity in ('all', 'month'):
            query = _builder_query(
                AggregationOperation.AVERAGE, granularity, ['StateName'], interval
            )
            native_rows = _rows(query, _post(port, query))
            sums = _reference(port, query, 'sum', 'doubleSum')
            counts = _reference(port, query, 'count', 'doubleSum')
            assert set(native_rows) == set(sums)
            for key, expected in sums.items():
                ratio = expected['value'] / counts[key]['value']
                assert native_rows[key][RESULT] == pytest.approx(ratio, rel=1e-12)


@pytest.mark.parametrize('port', PORTS)
@pytest.mark.parametrize(
    'operation',
    [
        AggregationOperation.SUM,
        AggregationOperation.COUNT,
        AggregationOperation.MAX,
        AggregationOperation.MIN,
    ],
)
def test_native_last_value_with_no_rows_is_legacy_zero(native, port, operation):
    '''A group another field keeps alive, where LAST_VALUE's own filter matches
    nothing, posts 0 as the extension does on legacy Druid. SUM, MAX and MIN
    have a `__count` that the client turns into null; COUNT has none.'''
    calculation = LastValueCalculation(
        filter=FieldFilter('no_such_field'), operation=operation
    ).to_druid(RESULT)
    other = LastValueCalculation(filter=FieldFilter(FIELD)).to_druid('other')
    calculation.add_aggregations(other.aggregations)
    query = (
        GroupByQueryBuilder(
            datasource=DATASOURCE,
            granularity='month',
            grouping_fields=['StateName'],
            intervals=[INTERVALS[1]],
            calculation=calculation,
        )
        .prepare()
        .query_dict
    )
    rows = _rows(query, _post(port, query))
    assert rows
    for row in rows.values():
        assert row[RESULT] == 0.0
        # 0 on legacy Druid, null under SQL-compatible nulls; absent for COUNT.
        assert not row.get(f'{RESULT}__count')


@pytest.mark.parametrize('port', sorted(EXTENSION_PORTS & set(PORTS)))
def test_native_and_extension_post_the_same_rows(monkeypatch, port):
    for operation, _metric, _combine, interval, granularity, grouping in _shapes():
        monkeypatch.setenv(LAST_VALUE_SETTING, 'extension')
        extension_query = _builder_query(operation, granularity, grouping, interval)
        monkeypatch.setenv(LAST_VALUE_SETTING, 'native')
        native_query = _builder_query(operation, granularity, grouping, interval)
        assert extension_query != native_query
        assert _post(port, native_query) == _post(port, extension_query), (
            operation,
            interval,
            granularity,
            grouping,
        )


def test_shapes_cover_every_operation_but_average():
    covered = {operation for operation, *_ in _shapes()}
    assert covered == set(AggregationOperation) - {AggregationOperation.AVERAGE}
