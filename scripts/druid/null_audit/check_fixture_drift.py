'''Show that the builder's posted Druid queries differ from the golden fixtures
only by the accepted WP-8a changes, and that no endpoint body changes.

    uv run python scripts/druid/null_audit/check_fixture_drift.py

The fixture queries are rewritten as the accepted changes describe, written here
independently of the builder code that implements them:
- N1: every `selector` with value `''` has value null;
- N2: under each `not`, every `selector` or `in` leaf reached through `and`/`or`
  (not through a nested `not`) becomes `and(leaf, not(selector dim null))`,
  unless it tests for null or `''`; a leaf's extractionFn goes onto the null test.
Both rewrites leave fixtures that already carry the change alone, so the check
holds before and after the fixtures are regenerated. The posted queries are then compared with the rewritten ones as canonical
queries. Exits non-zero on any other difference or any body change.
'''
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


def _guard(leaf: dict) -> dict:
    is_null = {'type': 'selector', 'dimension': leaf['dimension'], 'value': None}
    if 'extractionFn' in leaf:
        is_null['extractionFn'] = leaf['extractionFn']
    return {'type': 'not', 'field': is_null}


def _is_guarded(node: dict) -> bool:
    fields = node.get('fields', [])
    return (
        node.get('type') == 'and'
        and len(fields) == 2
        and any(
            other == _guard(leaf)
            for leaf, other in (fields, fields[::-1])
            if leaf.get('type') in ('selector', 'in')
        )
    )


def _guard_leaves(node: dict) -> dict:
    kind = node.get('type')
    if _is_guarded(node):
        return node
    if kind in ('and', 'or'):
        return {**node, 'fields': [_guard_leaves(field) for field in node['fields']]}
    if kind == 'selector':
        values = [node['value']]
    elif kind == 'in':
        values = node['values']
    else:
        return node
    if any(value in (None, '') for value in values):
        return node
    return {'type': 'and', 'fields': [node, _guard(node)]}


def accepted_rewrite(node: Any) -> Any:
    if isinstance(node, list):
        return [accepted_rewrite(item) for item in node]
    if not isinstance(node, dict):
        return node
    if node.get('type') == 'selector' and node.get('value') == '':
        return {**node, 'value': None}
    rewritten = {key: accepted_rewrite(value) for key, value in node.items()}
    if node.get('type') == 'not':
        rewritten['field'] = _guard_leaves(rewritten['field'])
    return rewritten


def main() -> int:
    bootstrap()
    changed = other = 0
    for case in load_cases():
        recorded = case.read('druid_query.json')
        responses = iter(case.read('druid_response.json'))
        posted, body = run_case(case, lambda _query, r=responses: next(r))
        posted_queries = [canonical_query(query) for query, _ in posted]
        recorded_queries = [canonical_query(query) for query in recorded]
        expected = [canonical_query(accepted_rewrite(q)) for q in recorded]
        if to_json_text(posted_queries) != to_json_text(recorded_queries):
            changed += 1
        if to_json_text(posted_queries) != to_json_text(expected):
            other += 1
            print(f'{case.name}: queries differ beyond the accepted changes')
        if to_json_text(body) != to_json_text(case.read('expected_response.json')):
            other += 1
            print(f'{case.name}: body differs')
    print(f'{changed} cases post changed queries; {other} other differences')
    return 1 if other else 0


if __name__ == '__main__':
    sys.exit(main())
