from types import SimpleNamespace
from unittest import mock

import pytest
from flask import g
from pydruid.utils.filters import Dimension, Filter

from db.druid.util import EmptyFilter
from web.server.routes.views.query_policy import AuthorizedQueryClient

POLICY = {'type': 'in', 'dimension': 'district', 'values': ['d1']}


class _SystemClient:
    def run_query(self, query):
        return Filter.build_filter(query.query_filter)


@pytest.fixture(autouse=True)
def fixture_request_context(bare_flask_app):
    with bare_flask_app().test_request_context():
        yield


def _filter_sent_to_druid(query_filter, policy=None, superuser=False):
    policy = Filter(**POLICY) if policy is None else policy
    query = SimpleNamespace(query_filter=query_filter)
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
        return AuthorizedQueryClient(_SystemClient()).run_query(query)


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
