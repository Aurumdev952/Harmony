'''An alert on a dimension skips rows where that dimension has no value (WP-8a N1).

Legacy Druid (`useDefaultValueForNull=true`) treats '' and null as one value, so
`selector value ''` and `selector value null` keep the same rows. Under
SQL-compatible nulls, the only mode from Druid 28 on, `value ''` matches only the
empty string, and the ingest transform (WP-8a N0) stores the pipeline's '' as
null. The guard must therefore test for null.
'''

import os
from typing import Optional

import pytest
from pydruid.utils.filters import Filter

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'alert-tests-not-a-secret')
os.environ.setdefault('DRUID_HOST', 'http://druid.alert-tests.invalid')

# pylint: disable=wrong-import-position
from data.alerts.alert import build_druid_filters, get_dimension_value_filters
from web.python_client.alerts_service.model import AlertDefinition

DIMENSION = 'StateName'
HAS_VALUE = {
    'type': 'not',
    'field': {'type': 'selector', 'dimension': DIMENSION, 'value': None},
}
LEGACY_GUARD = {
    'type': 'not',
    'field': {'type': 'selector', 'dimension': DIMENSION, 'value': ''},
}

# What each Druid stores for the pipeline's '', null and a real value.
# `legacy`: 0.23 as deployed. `sqlnull`: 0.23 with useDefaultValueForNull=false
# (two-valued filters). `druid38`: three-valued filters. Both SQL-compatible
# modes ingest with the N0 transform, so '' arrives as null.
STORED_VALUES = {
    'legacy': ['Kigali', '', None],
    'sqlnull': ['Kigali', None],
    'druid38': ['Kigali', None],
}


def _matches(node: dict, value: Optional[str], mode: str) -> Optional[bool]:
    '''Druid's native `selector` and `not` on one row; None is "unknown".'''
    if node['type'] == 'not':
        inner = _matches(node['field'], value, mode)
        return None if inner is None else not inner
    assert node['type'] == 'selector' and node['dimension'] == DIMENSION
    wanted = node['value']
    if mode == 'legacy':
        return (value or None) == (wanted or None)
    if value is None and wanted is not None:
        return None if mode == 'druid38' else False
    return value == wanted


def _kept(guard: dict, mode: str) -> list:
    return [v for v in STORED_VALUES[mode] if _matches(guard, v, mode) is True]


def _alert_guard() -> dict:
    alert_def = AlertDefinition(
        user_id='1',
        uri='/api2/alert_definitions/1',
        checks=[],
        time_granularity='month',
        fields=[],
        filters=[],
        title='alert on states',
        dimension_name=DIMENSION,
    )
    return Filter.build_filter(
        build_druid_filters(get_dimension_value_filters(alert_def))
    )


def test_alert_guard_tests_for_null():
    assert _alert_guard() == HAS_VALUE


@pytest.mark.parametrize('mode', sorted(STORED_VALUES))
def test_alert_guard_keeps_only_rows_with_a_value(mode):
    assert _kept(_alert_guard(), mode) == ['Kigali']


def test_legacy_rows_kept_are_unchanged():
    assert _kept(HAS_VALUE, 'legacy') == _kept(LEGACY_GUARD, 'legacy')


def test_legacy_guard_lets_null_rows_through_under_sql_nulls():
    assert _kept(LEGACY_GUARD, 'sqlnull') == ['Kigali', None]
