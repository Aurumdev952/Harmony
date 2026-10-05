'''A query policy that excludes values keeps the rows with no value (WP-8a N2, INV-3).

Exclusions in query policies become `not(in dim [...])`. On Druid 28 and later
three-valued logic would make that drop rows whose dimension is null, which
legacy Druid kept, so a policy would hide more than it does today. These tests
post real endpoint requests through `AuthorizedQueryClient` with a caller whose
needs exclude a value, and check every posted Druid query, nested ones
included, carries the exclusion in its two-valued form.
'''

import json
from unittest import mock

import pytest
from flask_principal import Identity

from tests.golden import harness

# The harness builds the caller from stored policy rows; _posted replaces it.
NO_STORED_POLICIES: dict = {'query_policies': []}


def _excluding_identity(dimension: str, value: str, other: str) -> Identity:
    # pylint: disable=import-outside-toplevel
    from models.python.permissions import DimensionFilter, QueryNeed

    identity = Identity('excluding-user')
    identity.provides.add(
        QueryNeed([DimensionFilter(dimension, exclude_values=[value])])
    )
    identity.provides.add(QueryNeed([DimensionFilter(other, all_values=True)]))
    return identity


def _posted(case_name: str, identity: Identity) -> list:
    case = next(c for c in harness.load_cases() if c.name == case_name)
    with mock.patch.object(harness, '_account_identity', lambda _policy: identity):
        exchanges, _ = harness.run_case(
            case, lambda _query: [], policy=NO_STORED_POLICIES
        )
    return [query for query, _ in exchanges]


def _filters(node):
    '''Every native filter in a posted query, nested ones included.'''
    if isinstance(node, list):
        for item in node:
            yield from _filters(item)
    elif isinstance(node, dict):
        if node.get('type') in ('not', 'and', 'or', 'in', 'selector'):
            yield node
        for value in node.values():
            yield from _filters(value)


def _exclusion(dimension: str, value: str) -> dict:
    return {
        'type': 'not',
        'field': {
            'type': 'and',
            'fields': [
                {'type': 'in', 'dimension': dimension, 'values': [value]},
                {
                    'type': 'not',
                    'field': {
                        'type': 'selector',
                        'dimension': dimension,
                        'value': None,
                    },
                },
            ],
        },
    }


def _bare_exclusion(dimension: str, value: str) -> dict:
    return {
        'type': 'not',
        'field': {'type': 'in', 'dimension': dimension, 'values': [value]},
    }


@pytest.mark.parametrize(
    ('dimension', 'value', 'other'),
    [
        # StateName is hierarchical in harmony_demo: `_construct_hierarchical_filter`.
        ('StateName', 'Pará', 'source'),
        # source is not: `_construct_single_filter`.
        ('source', 'yellow_fever', 'StateName'),
    ],
)
@pytest.mark.parametrize(
    'case_name', ['calc_last_value', 'calc_count_distinct_by_state']
)
def test_exclude_values_policy_keeps_rows_with_no_value(
    case_name, dimension, value, other
):
    queries = _posted(case_name, _excluding_identity(dimension, value, other))
    assert queries
    for query in queries:
        _assert_two_valued_exclusion(query, dimension, value)


def _assert_two_valued_exclusion(query: dict, dimension: str, value: str) -> None:
    filters = list(_filters(query.get('filter')))
    assert _exclusion(dimension, value) in filters, json.dumps(query)
    assert _bare_exclusion(dimension, value) not in filters, json.dumps(query)


def test_exact_unique_count_inner_query_keeps_rows_with_no_value():
    '''Exact COUNT_DISTINCT nests a query built from the builder's
    dimension_filter, which `run_query` ANDs the policy into separately. No
    golden case reaches it (harmony_demo's sketch sizes pick thetaSketch).'''
    # pylint: disable=import-outside-toplevel
    from flask import g
    from pydruid.utils.filters import Filter

    from db.druid.aggregations.exact_unique_count_aggregation import (
        ExactUniqueCountAggregation,
    )
    from db.druid.calculations.base_calculation import BaseCalculation
    from db.druid.query_builder import GroupByQueryBuilder
    from web.server.routes.views import query_policy

    harness.bootstrap()
    query = GroupByQueryBuilder(
        datasource='harmony_demo_20260101',
        granularity='all',
        grouping_fields=['StateName'],
        intervals=['2024-01-01/2024-04-01'],
        calculation=BaseCalculation(
            aggregations={
                'municipalities': ExactUniqueCountAggregation(
                    'MunicipalityName',
                    'municipalities',
                    count_filter=Filter(dimension='field', value='yellow_fever_cases'),
                )
            }
        ),
    )
    issued = []
    client = query_policy.AuthorizedQueryClient(
        mock.Mock(run_query=lambda q: issued.append(q.prepare().query_dict))
    )
    g.identity = _excluding_identity('StateName', 'Pará', 'source')
    try:
        with mock.patch.object(query_policy, 'is_public_dashboard_user', lambda: False):
            client.run_query(query)
    finally:
        del g.identity

    (posted,) = issued
    assert posted['dataSource']['type'] == 'query'
    _assert_two_valued_exclusion(posted['dataSource']['query'], 'StateName', 'Pará')
