'''Show that the builder's posted Druid queries differ from the golden fixtures
only by the WP-8a N1 change: every `selector` with value `''` now has value null.

    uv run python scripts/druid/null_audit/check_fixture_drift.py

For each golden case, the queries the current builder posts are compared with
`druid_query.json` after rewriting the fixture's `''` selectors to null. Exits
non-zero if any case differs in any other way, or if a body would change.
'''
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# pylint: disable=wrong-import-position
from tests.golden.harness import (
    bootstrap,
    canonical_query,
    load_cases,
    run_case,
    to_json_text,
)


def _null_selectors(node: Any) -> Any:
    if isinstance(node, list):
        return [_null_selectors(item) for item in node]
    if not isinstance(node, dict):
        return node
    if node.get('type') == 'selector' and node.get('value') == '':
        return {**node, 'value': None}
    return {key: _null_selectors(value) for key, value in node.items()}


def main() -> int:
    bootstrap()
    changed = other = 0
    for case in load_cases():
        recorded = case.read('druid_query.json')
        responses = iter(case.read('druid_response.json'))
        posted, body = run_case(case, lambda _query: next(responses))
        posted_queries = [canonical_query(query) for query, _ in posted]
        recorded_queries = [canonical_query(query) for query in recorded]
        expected = [canonical_query(_null_selectors(q)) for q in recorded]
        if to_json_text(posted_queries) != to_json_text(recorded_queries):
            changed += 1
        if to_json_text(posted_queries) != to_json_text(expected):
            other += 1
            print(f'{case.name}: queries differ beyond selector value null')
        if to_json_text(body) != to_json_text(case.read('expected_response.json')):
            other += 1
            print(f'{case.name}: body differs')
    print(f'{changed} cases post changed queries; {other} differences beyond N1')
    return 1 if other else 0


if __name__ == '__main__':
    sys.exit(main())
