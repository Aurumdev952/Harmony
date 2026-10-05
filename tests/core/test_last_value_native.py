'''LAST_VALUE builds without the aggregateLast extension when asked (WP-8a, N3).

The Zenysis `aggregateLast` extension exists for Druid 0.23 only and fails under
SQL-compatible nulls. With `HARMONY_DRUID_LAST_VALUE=native` the same wrapper is
serialised as Druid's built-in `expression` aggregator. These tests pin what is
posted; `tests/druid/test_last_value_live.py` proves the results on live Druid.
'''

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydruid.utils.aggregators import build_aggregators

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'core-tests-not-a-secret')
os.environ.setdefault('DRUID_HOST', 'http://druid.core-tests.invalid')

# pylint: disable=wrong-import-position
import db.druid.util  # noqa: F401  (installs the aggregator serialisation)
from data.query.models.calculation.last_value_calculation import (
    AggregationOperation,
    LastValueCalculation,
)
from data.query.models.query_filter import FieldFilter
from config import settings
from db.druid.aggregations.last_value_aggregation import (
    MAX_SIZE_BYTES,
    native_last_value,
)
from db.druid.calculations.complex_calculation import ComplexCalculation
from db.druid.calculations.simple_calculation import (
    LastValueCalculation as DruidLastValueCalculation,
)

FIELD = 'yellow_fever_cases'
GOLDEN_QUERY = (
    Path(__file__).parents[1] / 'golden/cases/calc_last_value/druid_query.json'
)


def _posted(calculation) -> dict:
    '''The posted aggregators, by name, as the query builder serialises them.'''
    built = build_aggregators(calculation.aggregations)
    return {_name(aggregator): aggregator for aggregator in built}


def _name(aggregator: dict) -> str:
    while 'name' not in aggregator:
        aggregator = aggregator['aggregator']
    return aggregator['name']


def _last_value(operation=AggregationOperation.SUM):
    return LastValueCalculation(
        filter=FieldFilter(FIELD), operation=operation
    ).to_druid(FIELD)


def _latest(time: str, value: str, combine: str, accumulator: str) -> str:
    acc_time = f'array_offset({accumulator}, 0)'
    acc_value = f'array_offset({accumulator}, 1)'
    return (
        f'if({time} > {acc_time}, array({time}, {value}), '
        f'if({time} == {acc_time}, '
        f'array({acc_time}, {combine.format(acc_value, value)}), '
        f'array({acc_time}, {acc_value})))'
    )


def _expected_native(
    name: str, metric: str, combine: str, accumulator: str = '__acc'
) -> dict:
    partial = f'"{name}"'
    return {
        'type': 'expression',
        'name': name,
        'fields': ['__time', metric],
        'accumulatorIdentifier': accumulator,
        'initialValue': 'array(-9007199254740992.0, 0.0)',
        'fold': _latest(
            'cast("__time", \'DOUBLE\')',
            f'nvl("{metric}", 0.0)',
            combine,
            accumulator,
        ),
        'combine': _latest(
            f'array_offset({partial}, 0)',
            f'array_offset({partial}, 1)',
            combine,
            accumulator,
        ),
        'isNullUnlessAggregated': False,
        'shouldCombineAggregateNullInputs': False,
        'finalize': 'array_offset(o, 1)',
        'maxSizeBytes': 32,
    }


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setattr(settings, 'DRUID_LAST_VALUE', 'native')


def test_extension_is_the_default(monkeypatch):
    '''Deployments on Druid 0.23 keep posting the extension until WP-8b.'''
    monkeypatch.setattr(settings, 'DRUID_LAST_VALUE', 'extension')
    golden = json.loads(GOLDEN_QUERY.read_text())[0]['aggregations'][0]
    assert _posted(_last_value())[FIELD] == golden


def test_native_sum_is_an_expression_aggregator(native):
    posted = _posted(_last_value())[FIELD]
    assert posted['type'] == 'filtered'
    assert posted['filter'] == {
        'type': 'selector',
        'dimension': 'field',
        'value': FIELD,
    }
    assert posted['aggregator'] == _expected_native(FIELD, 'sum', '{} + {}')


@pytest.mark.parametrize(
    ('operation', 'metric', 'combine'),
    [
        (AggregationOperation.COUNT, 'count', '{} + {}'),
        (AggregationOperation.MAX, 'max', 'greatest({}, {})'),
        (AggregationOperation.MIN, 'min', 'least({}, {})'),
    ],
)
def test_native_operations(native, operation, metric, combine):
    posted = _posted(_last_value(operation))[FIELD]
    assert posted['aggregator'] == _expected_native(FIELD, metric, combine)


def test_native_average_keeps_both_parts_and_the_ratio(native):
    calculation = _last_value(AggregationOperation.AVERAGE)
    posted = _posted(calculation)
    count_key = f'{FIELD}_count_for_average'
    sum_key = f'{FIELD}_sum_for_average'
    assert posted[count_key]['aggregator'] == _expected_native(
        count_key, 'count', '{} + {}'
    )
    assert posted[sum_key]['aggregator'] == _expected_native(sum_key, 'sum', '{} + {}')
    assert list(calculation.post_aggregations) == [FIELD]


def test_native_name_follows_a_renamed_calculation(native):
    '''The combine expression reads the aggregator by name, so it must use the
    name the query posts, not the one the calculation started with.'''
    renamed = ComplexCalculation.create_from_calculation(
        _last_value(), new_id=f'{FIELD}_total', original_id=FIELD
    )
    name = f'{FIELD}_total'
    assert _posted(renamed)[name]['aggregator'] == _expected_native(
        name, 'sum', '{} + {}'
    )


def test_native_config_aggregation_rule(native):
    '''Deployment aggregation rules build LAST_VALUE through the older class.'''
    calculation = DruidLastValueCalculation(dimension='field', field=FIELD)
    assert _posted(calculation)[FIELD]['aggregator'] == _expected_native(
        FIELD, 'sum', '{} + {}'
    )


def test_identifiers_are_quoted():
    built = native_last_value('a "b" \\ c', {'type': 'doubleSum', 'fieldName': 'sum'})
    assert 'array_offset("a \\"b\\" \\\\ c", 0)' in built['combine']


def test_unsupported_inner_aggregator_is_rejected():
    with pytest.raises(ValueError, match='longFirst'):
        native_last_value('x', {'type': 'longFirst', 'fieldName': 'sum'})


def _load_settings(value):
    '''`settings.DRUID_LAST_VALUE` in a fresh process, with the setting unset
    when `value` is None.'''
    environment = {**os.environ, 'HARMONY_DRUID_LAST_VALUE': value or ''}
    return subprocess.run(
        [
            sys.executable,
            '-c',
            'from config import settings; print(settings.DRUID_LAST_VALUE)',
        ],
        env=environment,
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )


def test_settings_default_to_the_extension():
    loaded = _load_settings(None)
    assert loaded.stdout.strip() == 'extension', loaded.stderr


def test_settings_read_native():
    loaded = _load_settings('native')
    assert loaded.stdout.strip() == 'native', loaded.stderr


def test_an_unknown_setting_fails_when_settings_load():
    '''A typo stops the process at startup instead of at the first query.'''
    loaded = _load_settings('Native')
    assert loaded.returncode != 0
    assert "HARMONY_DRUID_LAST_VALUE must be 'extension' or 'native'" in loaded.stderr


def test_the_accumulator_fits_in_max_size_bytes():
    '''Druid writes the accumulator as a nullable ARRAY<DOUBLE> of two: a null
    byte, a 4-byte length, then a null byte and 8 bytes per element.'''
    accumulator_bytes = 1 + 4 + 2 * (1 + 8)
    assert accumulator_bytes <= MAX_SIZE_BYTES < 1024


@pytest.mark.parametrize(
    ('name', 'metric', 'accumulator'),
    [
        ('__acc', 'sum', '___acc'),
        ('___acc', '__acc', '____acc'),
    ],
)
def test_native_accumulator_never_shadows_a_binding(name, metric, accumulator):
    '''`combine` binds the partial result to the aggregator's name and `fold`
    binds the fields. Either one named like the accumulator would hide it, and
    Druid would drop partial results.'''
    built = native_last_value(name, {'type': 'doubleSum', 'fieldName': metric})
    assert built == _expected_native(name, metric, '{} + {}', accumulator)
