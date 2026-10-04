from types import SimpleNamespace
from unittest import mock

import pytest
from pydruid.utils.filters import Dimension, Filter

from db.druid.util import EmptyFilter
from web.server.routes.views.query_policy import (
    restrict_query_filter_to_user_permissions,
)

POLICY = {'type': 'in', 'dimension': 'district', 'values': ['d1']}


def _restricted_filter(query_filter):
    query = SimpleNamespace(query_filter=query_filter)
    with mock.patch(
        'web.server.routes.views.query_policy._construct_authorization_filter',
        return_value=Filter(**POLICY),
    ):
        restrict_query_filter_to_user_permissions(query, user_identity=object())
    return Filter.build_filter(query.query_filter)


@pytest.mark.parametrize('query_filter', [EmptyFilter(), None])
def test_policy_alone_when_the_query_has_no_filter(query_filter):
    # Druid rejects {"type": "and", "fields": [null, ...]}.
    assert _restricted_filter(query_filter) == POLICY


def test_policy_is_anded_with_the_query_filter():
    selector = {'type': 'selector', 'dimension': 'field', 'value': 'x'}
    assert _restricted_filter(Dimension('field') == 'x') == {
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

    assert _restricted_filter(query_filter) == {
        'type': 'and',
        'fields': [{'type': 'and', 'fields': selectors}, POLICY],
    }
    assert Filter.build_filter(query_filter) == {'type': 'and', 'fields': selectors}
