'''Golden query suite (INV-2): each case's request must produce the recorded Druid
queries and, fed the recorded Druid responses, the recorded endpoint body.'''
from functools import lru_cache

import pytest

from tests.golden.harness import (
    RecordedDruid,
    dumps_compact,
    load_cases,
    run_case,
    to_json_text,
)

CASES = load_cases()
CASE_FILES = (
    'case.json',
    'request.json',
    'druid_query.json',
    'druid_response.json',
    'expected_response.json',
)
COMPLETE_CASES = [
    case for case in CASES if all((case.path / name).exists() for name in CASE_FILES)
]


@lru_cache(maxsize=None)
def replay(case_name: str):
    case = next(case for case in CASES if case.name == case_name)
    broker = RecordedDruid(
        case.read('druid_query.json'), case.read('druid_response.json')
    )
    return run_case(case, broker)


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.name)
def test_case_is_complete(case):
    missing = [name for name in CASE_FILES if not (case.path / name).exists()]
    assert not missing, f'run tests/golden/record.py {case.name}'


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.name)
def test_druid_queries(case):
    exchanges, _ = replay(case.name)
    posted = [query for query, _ in exchanges]
    recorded = case.read('druid_query.json')
    # Independent sub-queries may be issued in any order.
    if sorted(map(dumps_compact, posted)) != sorted(map(dumps_compact, recorded)):
        assert to_json_text(posted) == to_json_text(recorded)


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.name)
def test_response(case):
    _, body = replay(case.name)
    expected = (case.path / 'expected_response.json').read_text(encoding='utf-8')
    assert to_json_text(body) == expected


def _walk(node, parent_key=None):
    if isinstance(node, dict):
        yield parent_key, node
        for key, value in node.items():
            yield from _walk(value, key)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, parent_key)


def test_catalogue_covers_the_query_surface():
    '''Adding a route, calculation type, filter type or enabled granularity without
    a golden case fails here.'''
    # pylint: disable=import-outside-toplevel
    from flask import current_app

    from web.server.api.query.calculation_schema import CALCULATION_IMPL_SCHEMAS
    from web.server.api.query.query_filter_schema import QUERY_FILTER_IMPL_SCHEMAS

    routes = _post_routes()
    granularities = {g.id for g in current_app.query_data.granularities}

    endpoints, calculations, filters, grouped = set(), set(), set(), set()
    for case in COMPLETE_CASES:
        endpoints.add(case.meta['endpoint'])
        for key, node in _walk(case.read('request.json')):
            if key == 'calculation':
                calculations.add(node['type'])
            elif key in ('filter', 'field', 'fields') and 'type' in node:
                filters.add(node['type'])
            elif key == 'groups' and 'granularity' in node:
                grouped.add(node['granularity'])

    assert routes - endpoints == set()
    assert set(CALCULATION_IMPL_SCHEMAS) - calculations == set()
    assert set(QUERY_FILTER_IMPL_SCHEMAS) - filters == set()
    assert granularities - grouped == set()


def _post_routes():
    # pylint: disable=import-outside-toplevel
    from flask import current_app

    prefix = '/api2/query/'
    return {
        rule.rule[len(prefix) :]
        for rule in current_app.url_map.iter_rules()
        if rule.rule.startswith(prefix) and 'POST' in rule.methods
    }


@pytest.mark.parametrize('route', sorted(_post_routes()))
def test_policy_restricts_every_route(route):
    '''Some case on the route must post different Druid queries for its policy
    caller than for an administrator, so a route that stops applying the query
    policy fails a golden case.'''
    policy_cases = [
        case
        for case in COMPLETE_CASES
        if case.meta['endpoint'] == route and case.meta.get('policy') is not None
    ]
    assert policy_cases, f'no case on {route} has a policy'
    for case in policy_cases:
        as_policy = [query for query, _ in replay(case.name)[0]]
        broker = RecordedDruid(
            case.read('druid_query.json'), case.read('druid_response.json')
        )
        as_admin = [query for query, _ in run_case(case, broker, policy=None)[0]]
        if sorted(map(dumps_compact, as_policy)) != sorted(
            map(dumps_compact, as_admin)
        ):
            return
    pytest.fail(f'no policy case on {route} posts a query its admin replay does not')
