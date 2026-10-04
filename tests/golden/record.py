'''Regenerate golden fixtures from each case's `case.json` and `request.json`.

    uv run python tests/golden/record.py              # every case
    uv run python tests/golden/record.py bar_graph_sum_by_state_month  # named cases
    uv run python tests/golden/record.py --check      # verify, write nothing

Recording runs the current code and answers each Druid query with
`synth.synthesize`. It overwrites `druid_query.json`, `druid_response.json` and
`expected_response.json`. Read tests/golden/README.md before regenerating an
existing case: it changes what INV-2 compares against.
'''
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# pylint: disable=wrong-import-position
from tests.golden.harness import bootstrap, load_cases, run_case, to_json_text
from tests.golden.synth import synthesize

FIXTURES = ('druid_query.json', 'druid_response.json', 'expected_response.json')


def record(case) -> dict:
    options = case.meta.get('druid', {})
    exchanges, body = run_case(
        case, lambda query: synthesize(case.name, query, options)
    )
    return {
        'druid_query.json': [query for query, _ in exchanges],
        'druid_response.json': [response for _, response in exchanges],
        'expected_response.json': body,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('cases', nargs='*', help='case directory names; default all')
    parser.add_argument(
        '--check',
        action='store_true',
        help='re-record in memory and fail if any fixture would change',
    )
    args = parser.parse_args()

    bootstrap()
    cases = load_cases()
    unknown = set(args.cases) - {case.name for case in cases}
    if unknown:
        parser.error(f'unknown cases: {sorted(unknown)}')
    selected = [case for case in cases if not args.cases or case.name in args.cases]

    changed = []
    for case in selected:
        fixtures = record(case)
        for filename in FIXTURES:
            text = to_json_text(fixtures[filename])
            path = case.path / filename
            if path.exists() and path.read_text(encoding='utf-8') == text:
                continue
            changed.append(f'{case.name}/{filename}')
            if not args.check:
                path.write_text(text, encoding='utf-8')

    verb = 'would change' if args.check else 'written'
    for name in changed:
        print(f'{verb}: {name}')
    print(f'{len(selected)} cases, {len(changed)} fixture files {verb}')
    return 1 if args.check and changed else 0


if __name__ == '__main__':
    sys.exit(main())
