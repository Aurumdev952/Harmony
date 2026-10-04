'''Row-level authorisation: what AuthorizedQueryClient.run_query sends to Druid.

`AuthorizedQueryClient.run_raw_query` is not covered: WP-0c is deciding whether
it applies the policy (SEC-4), and its behaviour is pinned once that lands.
'''

from __future__ import annotations

import dataclasses
import os
from types import SimpleNamespace

import pytest
import yaml
from flask import Flask
from pydruid.utils.filters import Dimension

from tests.authz.druid_filters import compact, normalise_expected
from tests.authz.principals import configuration, load_identity, principal_specs
from web.server.routes.views.query_policy import AuthorizedQueryClient

_HERE = os.path.dirname(__file__)
SESSION_CLAIMS = {'needs': ['*'], 'query_needs': ['*']}
QUERY_OWN_FILTER = {'eq': ['field', 'indicator_1']}

with open(os.path.join(_HERE, 'query_policies.yaml')) as _stream:
    _TABLE = yaml.safe_load(_stream)


def _runs():
    for case in _TABLE['cases']:
        spec = principal_specs()[case.get('principal', 'no_roles')]
        if 'jwt' in case:
            yield case, 'token', dataclasses.replace(spec, jwt=case['jwt'])
        elif spec.jwt is not None or not spec.signed_in:
            yield case, 'declared', spec
        else:
            yield case, 'header', spec
            yield case, 'session', dataclasses.replace(spec, jwt=SESSION_CLAIMS)


RUNS = list(_runs())


def _zen_config(name: str, app: Flask):
    raw = _TABLE['configs'][name]
    if raw == 'real':
        return app.zen_config
    return SimpleNamespace(
        filters=SimpleNamespace(AUTHORIZABLE_DIMENSIONS=set(raw['authorizable'])),
        datatypes=SimpleNamespace(HIERARCHICAL_DIMENSIONS=list(raw['hierarchical'])),
    )


class RecordingDruidClient:
    def __init__(self):
        self.queries = []

    def run_query(self, query):
        self.queries.append(query)
        return 'druid result'


@pytest.mark.parametrize(
    'case,spec',
    [(case, spec) for case, _, spec in RUNS],
    ids=[f'{case["name"]}[{auth}]' for case, auth, _ in RUNS],
)
def test_run_query_filter(case, spec, app, request_ctx, monkeypatch):
    monkeypatch.setattr(
        app, 'zen_config', _zen_config(case.get('config', 'harmony_demo'), app)
    )
    load_identity(spec, case['policies'], case.get('group_policies', ()))
    druid = RecordingDruidClient()
    query = SimpleNamespace(query_filter=Dimension('field') == 'indicator_1')

    with configuration(spec.public_access):
        result = AuthorizedQueryClient(druid).run_query(query)

    assert result == 'druid result'
    (sent,) = druid.queries
    if case['expect'] is None:
        expected = QUERY_OWN_FILTER
    else:
        expected = normalise_expected({'and': [QUERY_OWN_FILTER, case['expect']]})
    assert compact(sent.query_filter) == expected


def test_every_case_name_is_unique():
    names = [case['name'] for case in _TABLE['cases']]
    assert len(names) == len(set(names))
