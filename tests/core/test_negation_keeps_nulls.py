'''A negated filter keeps the rows whose dimension is null (WP-8a, N2).

Legacy Druid evaluates native filters with two-valued logic: `Sex = F` is false
on a row with no Sex, so `NOT Sex = F` keeps that row. Druid 28 and later use
three-valued logic: the comparison is unknown, so is its negation, and the row
is dropped. Every value comparison under a `not` is therefore emitted as
`leaf AND NOT dimension IS NULL`, which is false, never unknown, on a null row,
and is the same filter as the bare leaf on legacy Druid.
'''

import os

from pydruid.utils.filters import Filter

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'core-tests-not-a-secret')
os.environ.setdefault('DRUID_HOST', 'http://druid.core-tests.invalid')

# pylint: disable=wrong-import-position
import db.druid.util  # noqa: F401  (installs the filter serialisation)
from data.query.models.query_filter import (
    AndFilter,
    InFilter,
    NotFilter,
    SelectorFilter,
)
from web.server.routes.views.query_policy import _construct_single_filter


def _is_null(dimension):
    return {'type': 'selector', 'dimension': dimension, 'value': None}


def _false_on_null(leaf):
    return {
        'type': 'and',
        'fields': [leaf, {'type': 'not', 'field': _is_null(leaf['dimension'])}],
    }


SEX_IS_F = {'type': 'selector', 'dimension': 'Sex', 'value': 'F'}
AGE_IN = {'type': 'in', 'dimension': 'Age', 'values': ['50+']}


def _built(query_filter):
    return Filter.build_filter(query_filter.to_druid())


def test_negated_selector_keeps_null_rows():
    built = _built(NotFilter(field=SelectorFilter(dimension='Sex', value='F')))
    assert built == {'type': 'not', 'field': _false_on_null(SEX_IS_F)}


def test_negated_in_keeps_null_rows():
    built = _built(NotFilter(field=InFilter(dimension='Age', values=['50+'])))
    assert built == {'type': 'not', 'field': _false_on_null(AGE_IN)}


def test_every_leaf_under_a_negated_conjunction_keeps_null_rows():
    built = _built(
        NotFilter(
            field=AndFilter(
                fields=[
                    SelectorFilter(dimension='Sex', value='F'),
                    InFilter(dimension='Age', values=['50+']),
                ]
            )
        )
    )
    assert built == {
        'type': 'not',
        'field': {
            'type': 'and',
            'fields': [_false_on_null(SEX_IS_F), _false_on_null(AGE_IN)],
        },
    }


def test_nested_negation_is_wrapped_once():
    built = _built(
        NotFilter(field=NotFilter(field=SelectorFilter(dimension='Sex', value='F')))
    )
    assert built == {
        'type': 'not',
        'field': {'type': 'not', 'field': _false_on_null(SEX_IS_F)},
    }


def test_has_value_test_is_unchanged():
    built = Filter.build_filter(~Filter(dimension='Sex', value=None))
    assert built == {'type': 'not', 'field': _is_null('Sex')}


def test_comparisons_that_match_null_on_legacy_are_unchanged():
    '''Legacy Druid reads '' as null, so these leaves already match null rows
    there; wrapping them would drop rows legacy kept out.'''
    empty = Filter(dimension='Sex', value='')
    in_with_empty = Filter(type='in', dimension='nation', values=['', 'x'])
    for leaf in (empty, in_with_empty):
        built = Filter.build_filter(~leaf)
        assert built == {'type': 'not', 'field': leaf.filter['filter']}


def test_extraction_function_is_kept_on_the_null_test():
    extraction = {'type': 'substring', 'index': 0, 'length': 1}
    leaf = Filter(dimension='Sex', value='F')
    leaf.filter['filter']['extractionFn'] = extraction
    built = Filter.build_filter(~leaf)
    raw_leaf = {**SEX_IS_F, 'extractionFn': extraction}
    assert built == {
        'type': 'not',
        'field': {
            'type': 'and',
            'fields': [
                raw_leaf,
                {
                    'type': 'not',
                    'field': {**_is_null('Sex'), 'extractionFn': extraction},
                },
            ],
        },
    }


def test_exclude_values_policy_keeps_rows_with_no_value():
    '''INV-3: a policy that excludes Pará has always shown rows with no state.'''
    policy_filter = _construct_single_filter(
        {'StateName': {'include': set(), 'exclude': {'Pará'}, 'all_values': False}}
    )
    leaf = {'type': 'in', 'dimension': 'StateName', 'values': ['Pará']}
    assert Filter.build_filter(policy_filter) == {
        'type': 'not',
        'field': _false_on_null(leaf),
    }


def _rebuilt(built):
    '''Calculations and the optimizers turn built filters back into pydruid
    filters (`build_filter_from_dict`) and build them again.'''
    return Filter.build_filter(db.druid.util.build_filter_from_dict(built))


def test_rebuilding_a_guarded_filter_does_not_guard_it_again():
    for query_filter in (
        NotFilter(field=SelectorFilter(dimension='Sex', value='F')),
        NotFilter(field=InFilter(dimension='Age', values=['50+'])),
        NotFilter(
            field=AndFilter(
                fields=[
                    SelectorFilter(dimension='Sex', value='F'),
                    NotFilter(field=InFilter(dimension='Age', values=['50+'])),
                ]
            )
        ),
    ):
        built = _built(query_filter)
        assert _rebuilt(built) == built
        assert _rebuilt(_rebuilt(built)) == built


def test_guarding_a_guarded_leaf_with_an_extraction_function_keeps_one_guard():
    '''`build_filter_from_dict` drops a selector's extractionFn (pydruid's
    `Filter` has no slot for it), so the guard is checked on its own output. No
    builder emits a leaf with an extractionFn today.'''
    leaf = Filter(dimension='Sex', value='F')
    leaf.filter['filter']['extractionFn'] = {'type': 'substring', 'index': 0}
    guarded = Filter.build_filter(~leaf)['field']
    # pylint: disable=protected-access
    assert db.druid.util._false_on_null(guarded) == guarded


def test_a_conjunction_that_only_looks_guarded_is_guarded():
    '''An `and` whose null test is on another dimension is not the guard.'''
    other_null = {'type': 'not', 'field': _is_null('Age')}
    built = Filter.build_filter(
        ~db.druid.util.build_filter_from_dict(
            {'type': 'and', 'fields': [SEX_IS_F, other_null]}
        )
    )
    assert built == {
        'type': 'not',
        'field': {'type': 'and', 'fields': [_false_on_null(SEX_IS_F), other_null]},
    }
