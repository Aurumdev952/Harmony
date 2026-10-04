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


@lru_cache(maxsize=None)
def replay(case_name: str):
    case = next(case for case in CASES if case.name == case_name)
    broker = RecordedDruid(case.read('druid_query.json'), case.read('druid_response.json'))
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
