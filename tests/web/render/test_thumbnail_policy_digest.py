"""WP-0i: two callers share a cached thumbnail only when their renders see the same data.

The digest is computed from the retrieve request's identity. The render runs
later under a render token (`query_needs: ['*']`) issued to the caller. Both
identities are built here through the real `signal_handlers` token path, and the
render's policy is the real Druid filter `query_policy` would apply.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Optional, Tuple

import pytest
from flask import g
from flask_principal import Identity
from pydruid.utils.filters import Filter

from models.python.permissions import DimensionFilter, QueryNeed
from tests.web.render.fakes import DASHBOARD_RESOURCE_ID, VIEW_DASHBOARD
from web.server.redis.thumbnail_storage_service import query_policy_fingerprint
from web.server.routes.views.query_policy import caller_policy_filter, canonical_policy
from web.server.security.permissions import SUPERUSER_NEED
from web.server.security.signal_handlers import (
    RENDER_TOKEN_QUERY_NEEDS,
    _compute_token_provides,
)

STATE, MUNICIPALITY, SOURCE = 'StateName', 'MunicipalityName', 'source'

LOGIN_CLAIMS = {'needs': ['*'], 'query_needs': ['*']}
RENDER_CLAIMS = {
    'needs': [['view_resource', DASHBOARD_RESOURCE_ID, 'dashboard']],
    'query_needs': RENDER_TOKEN_QUERY_NEEDS,
}


def need(**dimensions) -> QueryNeed:
    return QueryNeed(
        [DimensionFilter(dimension, **spec) for dimension, spec in dimensions.items()]
    )


ALL = {'all_values': True}


def only(*values):
    return {'include_values': values}


ACCOUNTS = {
    'superuser': {SUPERUSER_NEED},
    'superuser_with_policy': {SUPERUSER_NEED, need(StateName=only('North'))},
    'all_values': {need(StateName=ALL), need(source=ALL)},
    'north': {need(StateName=only('North'))},
    'north_and_all_states': {need(StateName=only('North')), need(StateName=ALL)},
    'all_states': {need(StateName=ALL)},
    'south': {need(StateName=only('South'))},
    'north_south_split': {need(StateName=only('North')), need(StateName=only('South'))},
    'north_south_joined': {need(StateName=only('North', 'South'))},
    'all_but_south': {
        need(StateName={'all_values': True, 'exclude_values': ['South']})
    },
    'municipality': {need(MunicipalityName=only('M1'))},
    'north_or_municipality': {
        need(StateName=only('North')),
        need(MunicipalityName=only('M1')),
    },
    'source': {need(source=only('X'))},
    'north_and_source_simple': {need(StateName=only('North')), need(source=only('X'))},
    'north_and_source_complex': {need(StateName=only('North'), source=only('X'))},
    'two_complex': {
        need(StateName=only('North'), source=only('X')),
        need(StateName=only('South'), source=only('Y')),
    },
    'unauthorisable_dimension_only': {need(DistrictName=only('D1'))},
    'no_policy': set(),
}


# Two hierarchical authorisable dimensions, so the hierarchical OR is exercised.
POLICY_ZEN_CONFIG = SimpleNamespace(
    filters=SimpleNamespace(AUTHORIZABLE_DIMENSIONS={STATE, MUNICIPALITY, SOURCE}),
    datatypes=SimpleNamespace(HIERARCHICAL_DIMENSIONS=[STATE, MUNICIPALITY]),
)


@pytest.fixture(name='policy_app')
def fixture_policy_app(app, renderer, monkeypatch):
    monkeypatch.setattr(app, 'zen_config', POLICY_ZEN_CONFIG)
    return app


def _identity(account, claims: Optional[dict]) -> Identity:
    identity = Identity('account')
    identity.provides = {VIEW_DASHBOARD} | set(account)
    g.identity = identity
    if claims is not None:
        identity.provides = _compute_token_provides(claims)
    return identity


def _canonical_filter(value):
    if isinstance(value, dict):
        canonical = {key: _canonical_filter(item) for key, item in value.items()}
        if isinstance(canonical.get('values'), list):
            canonical['values'] = sorted(canonical['values'], key=str)
        if isinstance(canonical.get('fields'), list):
            canonical['fields'] = sorted(canonical['fields'], key=json.dumps)
        return canonical
    if isinstance(value, list):
        return [_canonical_filter(item) for item in value]
    return value


def digest(account, claims: Optional[dict]) -> str:
    _identity(account, claims)
    return query_policy_fingerprint()


def render_filter(account) -> Optional[dict]:
    _identity(account, RENDER_CLAIMS)
    policy_filter = caller_policy_filter()
    if policy_filter is None:
        return None
    return _canonical_filter(Filter.build_filter(policy_filter))


def all_digests() -> Dict[Tuple[str, str], str]:
    """Each account's digest per sign-in channel."""
    return {
        (name, channel): digest(account, claims)
        for name, account in ACCOUNTS.items()
        for channel, claims in (('header', None), ('cookie', LOGIN_CLAIMS))
    }


@pytest.fixture(name='measured')
def fixture_measured(policy_app):
    """Each account's digest per sign-in channel and its render's filter."""
    with policy_app.test_request_context('/'):
        digests = all_digests()
        filters = {name: render_filter(account) for name, account in ACCOUNTS.items()}
    return digests, filters


def test_equal_digests_imply_equal_render_filters(measured):
    digests, filters = measured
    accounts_by_digest: Dict[str, set] = {}
    for (name, _channel), value in digests.items():
        accounts_by_digest.setdefault(value, set()).add(name)

    for names in accounts_by_digest.values():
        assert (
            len({json.dumps(filters[name], sort_keys=True) for name in names}) == 1
        ), names


def test_header_and_cookie_callers_of_one_account_share_a_digest(measured):
    digests, _filters = measured

    for name in ACCOUNTS:
        assert digests[(name, 'header')] == digests[(name, 'cookie')], name


@pytest.mark.parametrize(
    'first, second',
    [
        ('north_south_split', 'north_south_joined'),
        ('north_and_source_simple', 'north_and_source_complex'),
        ('north_and_all_states', 'all_states'),
        ('superuser', 'superuser_with_policy'),
    ],
)
def test_policies_that_render_alike_share_a_digest(measured, first, second):
    digests, filters = measured

    assert digests[(first, 'header')] == digests[(second, 'header')]
    assert filters[first] == filters[second]


@pytest.mark.parametrize(
    'first, second',
    [('north', 'south'), ('north', 'all_states'), ('north', 'superuser')],
)
def test_policies_that_render_differently_do_not_share_a_digest(
    measured, first, second
):
    digests, filters = measured

    assert digests[(first, 'header')] != digests[(second, 'header')]


# Run in a fresh interpreter, where PYTHONHASHSEED decides every set's order.
_DIGESTS_IN_A_FRESH_INTERPRETER = """
import json
from flask import Flask
from tests.web.render import test_thumbnail_policy_digest as digests

app = Flask('tests.web', root_path='.', instance_path='/tmp')
app.zen_config = digests.POLICY_ZEN_CONFIG
with app.test_request_context('/'):
    measured = digests.all_digests()
print(json.dumps(sorted([list(key), value] for key, value in measured.items())))
"""


def _digests_under_hash_seed(seed: str) -> Dict[Tuple[str, str], str]:
    repo_root = Path(__file__).resolve().parents[3]
    env = {**os.environ, 'PYTHONHASHSEED': seed, 'PYTHONPATH': str(repo_root)}
    output = subprocess.run(
        [sys.executable, '-c', _DIGESTS_IN_A_FRESH_INTERPRETER],
        cwd=repo_root,
        env=env,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    return {tuple(key): value for key, value in json.loads(output.splitlines()[-1])}


def test_digest_does_not_depend_on_the_hash_seed(measured):
    digests, _filters = measured

    assert _digests_under_hash_seed('1') == _digests_under_hash_seed('2') == digests


def test_digest_does_not_depend_on_query_need_order(policy_app):
    with policy_app.test_request_context('/'):
        north, all_states = need(StateName=only('North')), need(StateName=ALL)

        assert canonical_policy([north, all_states]) == canonical_policy([all_states])
        assert canonical_policy([all_states, north]) == canonical_policy([all_states])


@pytest.mark.xfail(
    strict=True,
    reason=(
        'Carried to WP-1h/5d: a token with narrowed query_needs digests the token, '
        'but the render token is re-resolved against the whole account.'
    ),
)
def test_narrowed_token_caller_digest_matches_their_render(policy_app):
    narrowed = {'needs': ['*'], 'query_needs': [{STATE: {'include_values': ['North']}}]}
    with policy_app.test_request_context('/'):
        caller_digest = digest(ACCOUNTS['all_values'], narrowed)
        north_digest = digest(ACCOUNTS['north'], None)
        wide_render = render_filter(ACCOUNTS['all_values'])
        north_render = render_filter(ACCOUNTS['north'])

    assert caller_digest != north_digest or wide_render == north_render
