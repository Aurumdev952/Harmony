from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest import mock

import pytest
from flask import g
from pydruid.utils.filters import Filter
from werkzeug.exceptions import BadRequest, NotFound

from db.druid.calculations.calculation_merger import CalculationMerger
from db.druid.calculations.simple_calculation import SumCalculation
from db.druid.query_builder import GroupByQueryBuilder
from web.server.routes.api import ApiRouter
from web.server.routes.views.field import MAX_FIELD_IDS_PER_REQUEST, FieldsApi

KNOWN_FIELDS = ('anc_visits', 'malaria_cases')
INTERVAL = '2020-01-01/2021-01-01'
POLICY = {'type': 'in', 'dimension': 'district', 'values': ['d1']}


def _get_calculation_for_fields(fields):
    # Same contract as config/<code>/aggregation_rules.py: unknown ids are skipped.
    return CalculationMerger(
        [SumCalculation('field', field) for field in fields if field in KNOWN_FIELDS]
    )


def _field_filter(field_id):
    query = GroupByQueryBuilder(
        '', 'month', [], [INTERVAL], _get_calculation_for_fields([field_id])
    )
    return Filter.build_filter(query.query_filter)


class _Lookups:
    '''Stands in for druid_context's time boundary and row count lookups.'''

    def __init__(self):
        self.calls = []

    def get_full_time_interval(self):
        return INTERVAL

    def get_filtered_time_boundary(self, query_filter=None, cache_key=None):
        self.calls.append(
            ('time_boundary', Filter.build_filter(query_filter), cache_key)
        )
        # Naive, like DataTimeBoundary's parse of Druid's minTime and maxTime.
        return {
            'min': datetime.fromisoformat('2020-01-01T00:00:00'),
            'max': datetime.fromisoformat('2020-12-01T00:00:00'),
        }

    def get_field_time_boundary(self, field_id, field_filter):
        return self.get_filtered_time_boundary(field_filter, f'field__{field_id}')

    def get_row_count(self, query_filter=None, cache_key=None):
        self.calls.append(('row_count', Filter.build_filter(query_filter), cache_key))
        return 42


@pytest.fixture(name='lookups')
def fixture_lookups():
    return _Lookups()


@pytest.fixture(name='request_field_info')
def fixture_request_field_info(bare_flask_app, lookups):
    app = bare_flask_app()
    app.druid_context = SimpleNamespace(
        data_time_boundary=lookups, row_count_lookup=lookups
    )
    app.zen_config = SimpleNamespace(
        aggregation_rules=SimpleNamespace(
            get_calculation_for_fields=_get_calculation_for_fields
        ),
        indicators=SimpleNamespace(GROUP_DEFINITIONS=[]),
    )

    def request(field_ids: str, restricted: bool):
        with app.test_request_context(f'/api/field/{field_ids}'), mock.patch(
            'web.server.routes.views.field.get_indicator_by_id', return_value=None
        ), mock.patch(
            'web.server.routes.views.query_policy.SuperUserPermission',
            return_value=SimpleNamespace(can=lambda: not restricted),
        ), mock.patch(
            'web.server.routes.views.query_policy.is_public_dashboard_user',
            return_value=False,
        ), mock.patch(
            'web.server.routes.views.query_policy._construct_authorization_filter',
            return_value=Filter(**POLICY),
        ):
            g.identity = object()
            router = ApiRouter(None, None, fields_api=FieldsApi(None))
            response = ApiRouter.api_field_info.__wrapped__(router, field_ids)
            return response.get_json()['data']

    return request


def test_unrestricted_caller_gets_the_same_queries_and_shared_cache(
    request_field_info, lookups
):
    # INV-2 and INV-3: callers who already saw everything see the same numbers.
    data = request_field_info('anc_visits', restricted=False)

    assert data['anc_visits']['count'] == 42
    assert data['anc_visits']['startDate'] == '2020-01-01'
    assert ('row_count', _field_filter('anc_visits'), 'anc_visits') in lookups.calls
    assert all(
        query_filter == _field_filter('anc_visits')
        for _, query_filter, _ in lookups.calls
    )


def test_restricted_caller_counts_only_their_slice_without_the_shared_cache(
    request_field_info, lookups
):
    request_field_info('anc_visits', restricted=True)

    assert {kind for kind, _, _ in lookups.calls} == {'time_boundary', 'row_count'}
    for _, query_filter, cache_key in lookups.calls:
        assert query_filter == {
            'type': 'and',
            'fields': [_field_filter('anc_visits'), POLICY],
        }
        # The row-count cache is process-wide and keyed by field: sharing it would
        # hand one user's numbers to the next.
        assert cache_key is None


@pytest.mark.parametrize('field_ids', ['no_such_field', 'anc_visits,no_such_field'])
def test_unknown_field_id_is_not_found_and_queries_nothing(
    request_field_info, lookups, field_ids
):
    # An unknown id used to give an empty filter: the whole datasource's numbers.
    with pytest.raises(NotFound):
        request_field_info(field_ids, restricted=True)
    assert not lookups.calls


def test_too_many_field_ids_is_a_bad_request(request_field_info, lookups):
    field_ids = ','.join(f'f{i}' for i in range(MAX_FIELD_IDS_PER_REQUEST + 1))
    with pytest.raises(BadRequest):
        request_field_info(field_ids, restricted=False)
    assert not lookups.calls


def test_several_known_ids_in_one_request(request_field_info):
    data = request_field_info('anc_visits,malaria_cases', restricted=False)
    assert set(data) == set(KNOWN_FIELDS)
