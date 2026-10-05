"""The enabled-dimensions probe tests "has a value" with a null selector (WP-8a N1)."""

import os

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'druid-tests-not-a-secret')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid:8082')

from scripts.data_catalog.compute_enabled_dimensions import (  # noqa: E402
    build_dimension_count_aggregation,
)


def test_dimension_count_aggregation_uses_a_null_selector():
    aggregation = build_dimension_count_aggregation('StateName')
    not_filter = aggregation['filter']
    assert not_filter['type'] == 'not'
    assert not_filter['field'] == {
        'type': 'selector',
        'dimension': 'StateName',
        'value': None,
    }
