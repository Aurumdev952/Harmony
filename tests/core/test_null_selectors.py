'''"Has no value" is `selector value null` in every query the builder emits (WP-8a).

Legacy Druid (`useDefaultValueForNull=true`) treats '' and null as the same
value, so `value ''` and `value null` match the same rows there. Under
SQL-compatible nulls, the only mode from Druid 28 on, `value ''` matches only the
empty string and lets null rows through.
'''

import os

from pydruid.utils.filters import Filter

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'core-tests-not-a-secret')
os.environ.setdefault('DRUID_HOST', 'http://druid.core-tests.invalid')

# pylint: disable=wrong-import-position
from data.query.models.dimension import GroupingDimension
from db.druid.aggregations.exact_unique_count_aggregation import (
    ExactUniqueCountAggregation,
)
from web.server.data.dimension_metadata_util.compute_sketch_sizes import (
    compute_eligible_high_cardinality_dimension_groupings,
)

HAS_VALUE = {
    'type': 'not',
    'field': {'type': 'selector', 'dimension': 'StateName', 'value': None},
}


def test_grouping_dimension_without_nulls_excludes_null_rows():
    grouping = GroupingDimension(dimension='StateName', include_null=False)
    assert Filter.build_filter(grouping.to_druid_filter()) == HAS_VALUE


def test_exact_unique_count_skips_null_values():
    aggregation = ExactUniqueCountAggregation('StateName', 'states')
    assert Filter.build_filter(aggregation.count_filter) == HAS_VALUE


class _RecordingClient:
    def __init__(self):
        self.queries = []

    def run_raw_query(self, query):
        self.queries.append(query)
        return []


def test_high_cardinality_probe_counts_only_rows_with_values():
    client = _RecordingClient()
    compute_eligible_high_cardinality_dimension_groupings(
        client, 'ds', ['2020-01-01/2021-01-01'], ['StateName'], ['MunicipalityName']
    )
    (query,) = client.queries
    assert query['filter'] == {
        'type': 'not',
        'field': {'type': 'selector', 'dimension': 'MunicipalityName', 'value': None},
    }
    assert query['aggregations'][0]['filter'] == HAS_VALUE
