from types import SimpleNamespace
from unittest import mock

import pytest
from flask import g
from pydruid.utils.filters import Dimension, Filter

from db.druid.calculations.calculation_merger import CalculationMerger
from db.druid.calculations.simple_calculation import SumCalculation
from db.druid.calculations.unique_calculations import ExactUniqueCountCalculation
from db.druid.query_builder import GroupByQueryBuilder
from db.druid.util import EmptyFilter
from web.server.routes.views.query_policy import AuthorizedQueryClient

POLICY = {'type': 'in', 'dimension': 'district', 'values': ['d1']}


class _FilterOnlySystemClient:
    def run_query(self, query):
        return Filter.build_filter(query.query_filter)


class _PreparingSystemClient:
    '''Returns the Druid query exactly as DruidQueryClient_.run_query sends it.'''

    def run_query(self, query):
        return query.prepare().query_dict


@pytest.fixture(autouse=True)
def fixture_request_context(bare_flask_app):
    with bare_flask_app().test_request_context():
        yield


def _run_as_caller(query, system_client, policy=None, superuser=False):
    policy = Filter(**POLICY) if policy is None else policy
    with mock.patch(
        'web.server.routes.views.query_policy.SuperUserPermission',
        return_value=SimpleNamespace(can=lambda: superuser),
    ), mock.patch(
        'web.server.routes.views.query_policy.is_public_dashboard_user',
        return_value=False,
    ), mock.patch(
        'web.server.routes.views.query_policy._construct_authorization_filter',
        return_value=policy,
    ):
        g.identity = object()
        return AuthorizedQueryClient(system_client).run_query(query)


def _filter_sent_to_druid(query_filter, policy=None, superuser=False):
    query = SimpleNamespace(query_filter=query_filter)
    return _run_as_caller(query, _FilterOnlySystemClient(), policy, superuser)


def _region_query(*calculations):
    return GroupByQueryBuilder(
        'ds',
        'month',
        ['district'],
        ['2020-01-01/2021-01-01'],
        CalculationMerger([SumCalculation('field', 'cases'), *calculations]),
        dimension_filter=Dimension('region') == 'r',
    )


@pytest.mark.parametrize('query_filter', [EmptyFilter(), None])
def test_policy_alone_when_the_query_has_no_filter(query_filter):
    # Druid rejects {"type": "and", "fields": [null, ...]}.
    assert _filter_sent_to_druid(query_filter) == POLICY


def test_policy_is_anded_with_the_query_filter():
    selector = {'type': 'selector', 'dimension': 'field', 'value': 'x'}
    assert _filter_sent_to_druid(Dimension('field') == 'x') == {
        'type': 'and',
        'fields': [selector, POLICY],
    }


def test_an_and_query_filter_is_wrapped_not_mutated():
    # pydruid's & appends into an existing "and" in place: that would change the
    # request shape (INV-2) and edit a filter other queries may share.
    selectors = [
        {'type': 'selector', 'dimension': 'field', 'value': 'x'},
        {'type': 'selector', 'dimension': 'region', 'value': 'r'},
    ]
    query_filter = (Dimension('field') == 'x') & (Dimension('region') == 'r')

    assert _filter_sent_to_druid(query_filter) == {
        'type': 'and',
        'fields': [{'type': 'and', 'fields': selectors}, POLICY],
    }
    assert Filter.build_filter(query_filter) == {'type': 'and', 'fields': selectors}


@pytest.mark.parametrize(
    'policy, superuser', [(Filter(**POLICY), True), (EmptyFilter(), False)]
)
def test_no_policy_leaves_the_query_filter_alone(policy, superuser):
    selector = {'type': 'selector', 'dimension': 'field', 'value': 'x'}
    sent = _filter_sent_to_druid(
        Dimension('field') == 'x', policy=policy, superuser=superuser
    )
    assert sent == selector


def test_policy_survives_a_query_modifying_aggregation():
    # ExactUniqueCount's modify_query moves filtering into an inner groupBy that
    # it rebuilds from dimension_filter, and clears the outer filter.
    sent = _run_as_caller(
        _region_query(ExactUniqueCountCalculation('facility', 'facilities')),
        _PreparingSystemClient(),
    )

    assert sent['filter'] is None
    assert POLICY in sent['dataSource']['query']['filter']['fields']


def test_ordinary_prepared_query_is_what_the_old_decorator_sent():
    # The decorator originally set query_filter = and[query_filter, policy] and
    # nothing else; queries without a modifier must still send exactly that.
    old_decorator_query = _region_query()
    old_decorator_query.query_filter = Filter(
        type='and', fields=[old_decorator_query.query_filter, Filter(**POLICY)]
    )

    sent = _run_as_caller(_region_query(), _PreparingSystemClient())

    assert sent == old_decorator_query.prepare().query_dict
    assert POLICY in sent['filter']['fields']
