from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

import pytest
from flask import g
from pydruid.utils.filters import Filter
from werkzeug.exceptions import BadRequest, NotFound

from db.druid.calculations.calculation_merger import CalculationMerger
from db.druid.calculations.simple_calculation import SumCalculation
from db.druid.query_builder import GroupByQueryBuilder
from models.python.permissions import DimensionFilter, QueryNeed
from web.server.data.row_count import RowCountLookup
from web.server.data.time_boundary import DataTimeBoundary
from web.server.routes.api import ApiRouter
from web.server.routes.views.field import MAX_FIELD_IDS_PER_REQUEST

# 'incomplete_ratio' is configured but every constituent is missing, so its
# calculation has no aggregations (INCOMPLETE_CALCULATED_INDICATORS).
CALCULATED_FIELDS = ('anc_visits', 'malaria_cases')
KNOWN_FIELDS = (*CALCULATED_FIELDS, 'incomplete_ratio')
FORMULAS = {
    'incomplete_ratio': 'missing_a / missing_b',
    'malaria_cases': 'confirmed + probable',
}
INTERVAL = '2020-01-01/2021-01-01'
DATASOURCE = SimpleNamespace(name='ds')
FULL_TIME_BOUNDARY = {
    'timestamp': '',
    'result': {'minTime': '2020-01-01T00:00:00', 'maxTime': '2020-12-31T00:00:00'},
}
DISTRICT_D1 = {'type': 'in', 'dimension': 'district', 'values': ['d1']}


def _get_calculation_for_fields(fields):
    # Same contract as config/<code>/aggregation_rules.py: unknown ids are skipped.
    return CalculationMerger(
        [
            SumCalculation('field', field)
            for field in fields
            if field in CALCULATED_FIELDS
        ]
    )


def _field_filter(field_id):
    query = GroupByQueryBuilder(
        '', 'month', [], [INTERVAL], _get_calculation_for_fields([field_id])
    )
    return Filter.build_filter(query.query_filter)


class _Druid:
    '''The system query client: records raw queries and answers like Druid.'''

    def __init__(self):
        self.queries = []

    def run_raw_query(self, query):
        query = {**query, 'filter': query.get('filter')}
        self.queries.append(query)
        if 'nowhere' in str(query['filter']):
            return []  # Druid's answer for a slice with no rows.
        if query['queryType'] == 'timeBoundary':
            return [
                {
                    'timestamp': '',
                    'result': {
                        'minTime': '2020-01-01T00:00:00.000Z',
                        'maxTime': '2020-12-01T00:00:00.000Z',
                    },
                }
            ]
        # Restricted callers see fewer rows: the count tells whose numbers came back.
        restricted = query['filter'].get('type') == 'and'
        return [{'result': {'count': 7 if restricted else 42}}]

    def filters(self, query_type):
        return [q['filter'] for q in self.queries if q['queryType'] == query_type]


@pytest.fixture(name='druid')
def fixture_druid():
    return _Druid()


@pytest.fixture(name='request_field_info')
def fixture_request_field_info(bare_flask_app, druid):
    app = bare_flask_app()
    # One RowCountLookup for the process, as druid_context's lru_cache gives.
    app.druid_context = SimpleNamespace(
        data_time_boundary=DataTimeBoundary(druid, DATASOURCE, FULL_TIME_BOUNDARY),
        row_count_lookup=RowCountLookup(druid, DATASOURCE),
    )
    app.zen_config = SimpleNamespace(
        aggregation_rules=SimpleNamespace(
            get_calculation_for_fields=_get_calculation_for_fields
        ),
        indicators=SimpleNamespace(
            ID_LOOKUP={field: {'id': field, 'text': field} for field in KNOWN_FIELDS},
            GROUP_DEFINITIONS=[],
        ),
        calculated_indicators=SimpleNamespace(CALCULATED_INDICATOR_FORMULAS=FORMULAS),
        filters=SimpleNamespace(AUTHORIZABLE_DIMENSIONS=['district']),
        datatypes=SimpleNamespace(HIERARCHICAL_DIMENSIONS=[]),
    )

    def request(field_ids: str, district: str | None):
        '''district=None is a site administrator; otherwise a policy for one district.'''
        provides = set()
        if district:
            provides.add(QueryNeed([DimensionFilter('district', [district])]))
        contexts = (
            app.test_request_context(f'/api/field/{field_ids}'),
            mock.patch(
                'web.server.routes.views.query_policy.SuperUserPermission',
                return_value=SimpleNamespace(can=lambda: district is None),
            ),
            mock.patch(
                'web.server.routes.views.query_policy.is_public_dashboard_user',
                return_value=False,
            ),
            mock.patch(
                'web.server.routes.views.authentication.current_user',
                SimpleNamespace(is_authenticated=True, is_active=True),
            ),
            mock.patch(
                'web.server.routes.views.authentication.get_user_string',
                lambda user: 'u',
            ),
            mock.patch(
                'web.server.routes.views.authentication.get_configuration',
                return_value=False,
            ),
        )
        with ExitStack() as stack:
            for context in contexts:
                stack.enter_context(context)
            g.identity = SimpleNamespace(provides=provides)
            response = ApiRouter(None, None).api_field_info(field_ids)
            return response.get_json()['data']

    return request


def test_unrestricted_caller_gets_the_same_queries_and_numbers(
    request_field_info, druid
):
    # INV-2 and INV-3: callers who already saw everything see the same numbers.
    data = request_field_info('anc_visits', district=None)

    assert data['anc_visits']['count'] == 42
    assert data['anc_visits']['startDate'] == '2020-01-01'
    assert druid.filters('timeBoundary') == [_field_filter('anc_visits')]
    assert druid.filters('timeseries') == [_field_filter('anc_visits')]


def test_restricted_caller_counts_only_their_slice(request_field_info, druid):
    data = request_field_info('anc_visits', district='d1')

    assert data['anc_visits']['count'] == 7
    sliced = {'type': 'and', 'fields': [_field_filter('anc_visits'), DISTRICT_D1]}
    assert druid.filters('timeBoundary') == [sliced]
    assert druid.filters('timeseries') == [sliced]


def test_users_never_see_each_others_cached_counts(request_field_info):
    # The row-count cache is process-wide and keyed by field id.
    assert request_field_info('anc_visits', district=None)['anc_visits']['count'] == 42
    assert request_field_info('anc_visits', district='d1')['anc_visits']['count'] == 7
    assert request_field_info('anc_visits', district=None)['anc_visits']['count'] == 42


def test_empty_slice_has_no_numbers_but_keeps_the_formula(request_field_info, druid):
    data = request_field_info('malaria_cases', district='nowhere')

    assert data['malaria_cases'] == {
        'count': 0,
        'startDate': None,
        'endDate': None,
        'formula': FORMULAS['malaria_cases'],
        'humanReadableFormulaHtml': 'confirmed + probable',
    }
    assert not druid.filters('timeseries')


def test_known_field_without_a_filter_queries_nothing_but_keeps_its_formula(
    request_field_info, druid
):
    # An empty filter would count every row the caller can see.
    data = request_field_info('incomplete_ratio', district='d1')

    assert data['incomplete_ratio']['count'] == 0
    assert data['incomplete_ratio']['formula'] == FORMULAS['incomplete_ratio']
    assert not druid.queries


@pytest.mark.parametrize('field_ids', ['no_such_field', 'anc_visits,no_such_field'])
def test_unknown_field_id_is_not_found_and_queries_nothing(
    request_field_info, druid, field_ids
):
    with pytest.raises(NotFound):
        request_field_info(field_ids, district='d1')
    assert not druid.queries


def test_too_many_field_ids_is_a_bad_request(request_field_info, druid):
    field_ids = ','.join(
        f'{KNOWN_FIELDS[0]}{i}' for i in range(MAX_FIELD_IDS_PER_REQUEST + 1)
    )
    with pytest.raises(BadRequest):
        request_field_info(field_ids, district=None)
    assert not druid.queries


def test_several_known_ids_in_one_request(request_field_info):
    data = request_field_info(','.join(CALCULATED_FIELDS), district=None)
    assert set(data) == set(CALCULATED_FIELDS)
