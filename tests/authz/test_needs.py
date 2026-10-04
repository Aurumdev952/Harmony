'''Need algebra and JWT narrowing.

`QueryNeed` containment (`in`) and intersection (`&`) decide what a token may
keep of an account's query policies (`_compute_token_query_needs`) and what
`QueryPermission` allows. `_compute_token_item_needs` decides which item needs
survive a token.
'''

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest
from flask import g
from flask_principal import ItemNeed, RoleNeed
from hypothesis import given
from hypothesis import strategies as st

from models.python.permissions import DimensionFilter, QueryNeed
from tests.authz.principals import load_identity, principal_specs
from web.server.security.permissions import QueryPermission

ALL = 'all'


def dimension(name, values):
    '''`values` is a list of included values, ALL, or ('all_except', [...]).'''
    if values == ALL:
        return DimensionFilter(name, all_values=True)
    if isinstance(values, tuple):
        return DimensionFilter(name, exclude_values=values[1], all_values=True)
    return DimensionFilter(name, include_values=values)


def need(**dimensions):
    return QueryNeed([dimension(name, values) for name, values in dimensions.items()])


# (required, held, held covers required)
# `{S1} in {all except S9}` is False even though an all-but-S9 holder clearly
# covers S1: DimensionFilter.__contains__ (models/python/permissions.py:261-263)
# only compares excludes as subsets and never widens an all-values holder to the
# concrete value. An inverted containment: recorded as today (finding Q8-adjacent,
# owner WP-4e), not a test bug.
CONTAINMENT = [
    (need(source=['S1']), need(source=['S1', 'S2']), True),
    (need(source=['S1', 'S2']), need(source=['S1']), False),
    (need(source=['S1']), need(source=ALL), True),
    (need(source=ALL), need(source=['S1']), False),
    (need(source=ALL), need(source=ALL), True),
    (
        need(source=['S1']),
        need(source=('all_except', ['S9'])),
        False,
    ),  # inverted; see above
    (need(source=['S9']), need(source=('all_except', ['S9'])), False),
    (need(source=['S1']), need(source=['S1'], StateName=['A']), True),
    (need(source=['S1'], StateName=['A']), need(source=ALL), False),
    (need(StateName=['A']), need(source=['S1']), False),
    (QueryNeed([]), need(source=['S1']), True),
    (need(source=['S1']), QueryNeed([]), False),
]


@pytest.mark.parametrize('required,held,expected', CONTAINMENT)
def test_query_need_containment(required, held, expected):
    assert (required in held) is expected


# Property oracle for the well-behaved region only: single-dimension,
# include-only needs, where a QueryNeed models a set of allowed values. `&` is
# intersection and `required in held` is "held's set is a superset". The
# all-values and exclude regions are deliberately excluded: that is where the
# algebra diverges (Q3, Q8, the inverted CONTAINMENT row), and a property over
# the full domain would fail on today's code. WP-4e, which fixes the algebra,
# owns widening this oracle.
_value_sets = st.lists(st.sampled_from('ABCDE'), min_size=1, max_size=5).map(set)


@given(a=_value_sets, b=_value_sets)
def test_include_only_intersection_matches_the_set_model(a, b):
    combined = need(d=sorted(a)) & need(d=sorted(b))
    expected = a & b
    if expected:
        (dim_filter,) = combined.dimension_filters
        assert dim_filter.include_values == expected
    else:
        # No overlap collapses to an empty include set (deny), which carries no
        # dimension filter in the resulting QueryNeed.
        assert combined.dimension_filters == [] or not any(
            f.include_values for f in combined.dimension_filters
        )


@given(required=_value_sets, held=_value_sets)
def test_include_only_containment_matches_superset(required, held):
    assert (need(d=sorted(required)) in need(d=sorted(held))) is held.issuperset(
        required
    )


# (token need, account need, intersection)
INTERSECTION = [
    (need(source=ALL), need(source=['S1']), need(source=['S1'])),
    (need(source=['S1', 'S2']), need(source=['S1']), need(source=['S1'])),
    (need(source=['S3']), need(source=['S1']), need(source=[])),
    (need(source=('all_except', ['S9'])), need(source=ALL), need(source=ALL)),
    (
        need(source=('all_except', ['S9'])),
        need(source=['S1', 'S9']),
        need(source=['S1', 'S9']),
    ),
    (need(source=['S1']), need(StateName=['A']), QueryNeed([])),
    (need(source=['S1'], StateName=['A']), need(source=ALL), need(source=['S1'])),
]


@pytest.mark.parametrize('token,account,expected', INTERSECTION)
def test_query_need_intersection(token, account, expected):
    assert (token & account) == expected


# QueryPermission has no caller today (AuthorizedQuery is unused); recorded so
# a port that revives it starts from the same semantics.
# (required needs, identity provides, allowed)
QUERY_PERMISSION = [
    ([need(source=['S1'])], {need(source=['S1', 'S2'])}, True),
    ([need(source=['S3'])], {need(source=['S1', 'S2'])}, False),
    ([need(source=['S1'], StateName=['X'])], {need(source=ALL)}, False),
    ([need(source=['S3'])], {RoleNeed('admin')}, True),
    ([need(source=['S1'])], set(), False),
]


@pytest.mark.parametrize('required,provides,expected', QUERY_PERMISSION)
def test_query_permission(required, provides, expected):
    identity = SimpleNamespace(provides=provides)
    assert QueryPermission(required).allows(identity) is expected


HEADER_PRINCIPALS = [
    name
    for name, spec in principal_specs().items()
    if spec.signed_in and spec.jwt is None
]


@pytest.mark.parametrize('name', HEADER_PRINCIPALS)
def test_browser_session_keeps_every_account_item_need(name, request_ctx):
    spec = principal_specs()[name]
    header = load_identity(spec).provides
    session = load_identity(
        dataclasses.replace(spec, jwt={'needs': ['*'], 'query_needs': ['*']})
    ).provides

    def items(needs):
        return {n for n in needs if not isinstance(n, QueryNeed)}

    assert items(session) == items(header)


VIEW_7 = ['view_resource', 7, 'dashboard']
VIEW_ALL_DASHBOARDS = ['view_resource', None, 'dashboard']

# (account principal, token `needs` claim, item needs the identity ends with)
TOKEN_ITEM_NEEDS = [
    ('role:admin', [VIEW_7], {ItemNeed(*VIEW_7)}),
    ('dashboard_acl_viewer', [VIEW_7], {ItemNeed(*VIEW_7)}),
    ('no_roles', [VIEW_7], set()),
    ('role:dashboard_viewer', [VIEW_7], {ItemNeed(*VIEW_7)}),
    ('dashboard_owner', [VIEW_ALL_DASHBOARDS], {ItemNeed(*VIEW_7)}),
    ('role:dashboard_viewer', [VIEW_ALL_DASHBOARDS], {ItemNeed(*VIEW_ALL_DASHBOARDS)}),
    ('role:dashboard_admin', [], set()),
]


@pytest.mark.parametrize('name,token_needs,expected', TOKEN_ITEM_NEEDS)
def test_explicit_token_item_needs(name, token_needs, expected, request_ctx):
    spec = principal_specs()[name]
    load_identity(
        dataclasses.replace(spec, jwt={'needs': token_needs, 'query_needs': ['*']})
    )

    assert {n for n in g.identity.provides if not isinstance(n, QueryNeed)} == expected
