'''Merging exact unique counts refuses incompatible inputs with an exception that
survives `python -O`, which strips asserts.'''

import os

import pytest

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'core-tests-not-a-secret')
os.environ.setdefault('DRUID_HOST', 'http://druid.core-tests.invalid')

# pylint: disable=wrong-import-position
from db.druid.aggregations.exact_unique_count_aggregation import (
    ExactUniqueCountAggregation,
)


def test_counts_on_one_dimension_merge():
    states = ExactUniqueCountAggregation('StateName', 'states')
    merged = states.merge_compatible_aggregation(
        ExactUniqueCountAggregation('StateName', 'other_states')
    )
    assert set(merged.calculation.outer_aggregations) == {'states', 'other_states'}
    assert set(states.calculation.outer_aggregations) == {'states'}


def test_counts_on_different_dimensions_do_not_merge():
    states = ExactUniqueCountAggregation('StateName', 'states')
    with pytest.raises(ValueError, match='dimension does not match'):
        states.merge_compatible_aggregation(
            ExactUniqueCountAggregation('MunicipalityName', 'municipalities')
        )


def test_other_modifiers_do_not_merge():
    states = ExactUniqueCountAggregation('StateName', 'states')
    with pytest.raises(TypeError, match='Invalid type'):
        states.merge_compatible_aggregation(object())


def test_conflicting_outer_aggregations_do_not_merge():
    states = ExactUniqueCountAggregation('StateName', 'states')
    conflicting = ExactUniqueCountAggregation(
        'StateName', 'states', exclude_missing=False
    )
    with pytest.raises(ValueError, match='overwrite existing outer aggregation'):
        states.merge_compatible_aggregation(conflicting)
