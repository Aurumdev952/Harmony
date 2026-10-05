'''A stored or submitted filter value '' is posted as null (WP-8a, DATA-1).

Stored dimension values write "no value" as '': a municipality whose state is
unknown is `MunicipalityName = X AND StateName = ''`
(`data/query/mock/__init__.py`, run by `update_db_datasource.py`). The client and
saved specs send these filters back unchanged. Legacy Druid
(`useDefaultValueForNull=true`) stores '' as null, so `value ''` matches the rows
with no value. Under SQL-compatible nulls, the only mode from Druid 28 on, it
matches no row. Building '' as null keeps the legacy meaning in every mode.
'''

import os

from pydruid.utils.filters import Filter

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'core-tests-not-a-secret')
os.environ.setdefault('DRUID_HOST', 'http://druid.core-tests.invalid')

# pylint: disable=wrong-import-position
from data.query.models import DimensionValue
from data.query.models.filter_items import DimensionValueFilterItem
from data.query.models.query_filter import (
    AndFilter,
    InFilter,
    NotFilter,
    SelectorFilter,
)
from db.druid.query_builder_util.optimization.filter_optimizations import (
    optimize_query_filter,
)
from db.druid.util import build_query_filter_from_aggregations, get_dimension_filters

NO_STATE = {'type': 'selector', 'dimension': 'StateName', 'value': None}
RIO_BRANCO = {
    'type': 'selector',
    'dimension': 'MunicipalityName',
    'value': 'Rio Branco',
}


def _built(query_filter):
    return Filter.build_filter(query_filter.to_druid())


def test_empty_selector_is_the_null_selector():
    assert _built(SelectorFilter(dimension='StateName', value='')) == NO_STATE


def test_other_selector_values_are_unchanged():
    assert _built(SelectorFilter(dimension='StateName', value='Acre')) == {
        'type': 'selector',
        'dimension': 'StateName',
        'value': 'Acre',
    }


def test_empty_value_in_an_in_filter_is_null():
    in_filter = InFilter(dimension='StateName', values=['Acre', ''])
    assert _built(in_filter) == {
        'type': 'in',
        'dimension': 'StateName',
        'values': ['Acre', None],
    }


def test_stored_geo_value_with_no_parent_tests_the_parent_for_null():
    stored = AndFilter(
        fields=[
            SelectorFilter(dimension='MunicipalityName', value='Rio Branco'),
            SelectorFilter(dimension='StateName', value=''),
        ]
    )
    item = DimensionValueFilterItem(
        id='municipality',
        dimension='MunicipalityName',
        dimension_values=[
            DimensionValue(
                id='rio-branco',
                dimension='MunicipalityName',
                name='Rio Branco',
                filter=stored,
            )
        ],
    )
    assert Filter.build_filter(item.build_filter().to_druid()) == {
        'type': 'and',
        'fields': [RIO_BRANCO, NO_STATE],
    }


def test_negated_empty_values_keep_the_has_value_form():
    '''A null test needs no three-valued guard (N2): it is never unknown.'''
    assert _built(NotFilter(field=SelectorFilter(dimension='StateName', value=''))) == {
        'type': 'not',
        'field': NO_STATE,
    }
    negated_in = NotFilter(field=InFilter(dimension='StateName', values=['Acre', '']))
    assert _built(negated_in) == {
        'type': 'not',
        'field': {'type': 'in', 'dimension': 'StateName', 'values': ['Acre', None]},
    }


def test_optimizer_keeps_a_null_selector_apart_from_the_text_none():
    query_filter = Filter(
        type='or',
        fields=[
            SelectorFilter(dimension='StateName', value='').to_druid(),
            SelectorFilter(dimension='StateName', value='None').to_druid(),
            InFilter(dimension='StateName', values=['Acre', '']).to_druid(),
            InFilter(dimension='StateName', values=['', 'Acre']).to_druid(),
        ],
    )
    optimized = Filter.build_filter(optimize_query_filter(query_filter))
    assert optimized == {
        'type': 'or',
        'fields': [
            NO_STATE,
            {'type': 'selector', 'dimension': 'StateName', 'value': 'None'},
            {'type': 'in', 'dimension': 'StateName', 'values': ['Acre', None]},
        ],
    }


def _filtered_sum(query_filter):
    return {
        'type': 'filtered',
        'filter': Filter.build_filter(query_filter.to_druid()),
        'aggregator': {'type': 'doubleSum', 'fieldName': 'sum'},
    }


def test_dimension_filters_collect_null():
    merged = (
        SelectorFilter(dimension='StateName', value='').to_druid()
        | InFilter(dimension='StateName', values=['Acre', 'Pará']).to_druid()
    )
    values, _, optimizable = get_dimension_filters(merged)
    assert optimizable
    assert values == {'StateName': {None, 'Acre', 'Pará'}}


def test_query_filter_from_aggregations_puts_null_first():
    aggregations = {
        'no_state': _filtered_sum(SelectorFilter(dimension='StateName', value='')),
        'states': _filtered_sum(
            InFilter(dimension='StateName', values=['Pará', 'Acre'])
        ),
    }
    query_filter = build_query_filter_from_aggregations(aggregations)
    assert Filter.build_filter(query_filter) == {
        'type': 'in',
        'dimension': 'StateName',
        'values': [None, 'Acre', 'Pará'],
    }


def test_query_filter_from_one_null_aggregation_is_the_null_selector():
    aggregations = {
        'no_state': _filtered_sum(SelectorFilter(dimension='StateName', value=''))
    }
    query_filter = build_query_filter_from_aggregations(aggregations)
    assert Filter.build_filter(query_filter) == NO_STATE
