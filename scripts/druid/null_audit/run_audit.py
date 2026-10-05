'''Replay every golden case against a real Druid and diff null semantics.

    AUDIT=scripts/druid/null_audit/run_audit.py
    uv run python $AUDIT index  --port 58891 [--raw]
    uv run python $AUDIT replay --port 58891 --out OUT/legacy [--candidate] [CASE...]
    uv run python $AUDIT diff OUT/legacy OUT/sqlnull
    uv run python $AUDIT parity --port 58891 [--js]

`index` loads make_dataset's rows into `harmony_demo_20260101` with the
production data schema (db/druid/indexing/common.py), or without its
''-to-null transform with `--raw`, and waits until the new segments are served.

`replay` POSTs each golden case and each audit case (cases/) through the golden
harness (tests/golden/harness.py), answering the app's Druid queries from the
live broker, and stores the app's queries, the raw Druid rows and the endpoint
body per case. `--candidate` rewrites each query on its way to Druid as the
builder fixes requested from core would build it (`candidate_filters`).

`diff` lists every case whose raw Druid rows or endpoint body differ between
two replays, with the first differing paths.

`parity` groups every day from 1900 to 2100 by the native epi week extraction
(tests/druid/epi_week.py) and, with `--js`, by the JavaScript one it replaces,
and fails unless both agree with each other and with the Python port.

The golden fixtures are not touched: their responses are synthetic, so the
audit is differential, the same data under two Druid configurations.
'''
import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, List, Tuple

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# pylint: disable=wrong-import-position
from scripts.druid.null_audit.legacy_js import WHO_EPI_WEEK_EXTRACTION_FORMULA
from tests.druid.epi_week import epi_week_of_year_extraction, js_epi_week_of_year
from tests.golden.harness import (
    DEPLOYMENT,
    DATASOURCE_DATE,
    Case,
    bootstrap,
    load_cases,
    run_case,
    to_json_text,
)

TASK_TIMEOUT_S = 900
QUERY_TIMEOUT_S = 120
AUDIT_CASES_DIR = Path(__file__).parent / 'cases'


def audit_cases() -> List[Case]:
    '''Null shapes the golden catalogue does not reach: a negated filter on a
    dimension that is null on some rows and not grouped, count distinct over such
    a dimension, and a kept null group. Same format as tests/golden/cases, minus
    the recorded fixtures.'''
    return [
        Case(path.name, path)
        for path in sorted(AUDIT_CASES_DIR.iterdir())
        if path.is_dir()
    ]


def _router(port: int) -> str:
    return f'http://127.0.0.1:{port}'


def _datasource() -> str:
    # pylint: disable=import-outside-toplevel
    from db.druid.datasource import SiteDruidDatasource

    return SiteDruidDatasource(DEPLOYMENT, DATASOURCE_DATE).name


def index_task(datasource: str, raw: bool) -> dict:
    # pylint: disable=import-outside-toplevel
    from db.druid.indexing.common import build_data_schema

    data_schema = build_data_schema(
        datasource, datetime(2018, 1, 1), datetime(2026, 1, 1)
    )
    if raw:
        del data_schema['transformSpec']
    return {
        'type': 'index_parallel',
        'spec': {
            'dataSchema': data_schema,
            'ioConfig': {
                'type': 'index_parallel',
                'inputSource': {
                    'type': 'local',
                    'baseDir': '/audit-data',
                    'filter': 'rows.json',
                },
                'inputFormat': {'type': 'json'},
            },
            'tuningConfig': {
                'type': 'index_parallel',
                'partitionsSpec': {'type': 'hashed', 'numShards': 1},
                'forceGuaranteedRollup': True,
                'maxNumConcurrentSubTasks': 1,
            },
        },
    }


def _wait(what: str, check, timeout_s: int) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = check()
        if result is not None:
            return result
        time.sleep(2)
    raise TimeoutError(f'timed out waiting for {what}')


def index(port: int, raw: bool) -> None:
    datasource = _datasource()
    _run_index_task(_router(port), datasource, index_task(datasource, raw))


def _sql(base: str, query: str, *parameters: str) -> list:
    response = requests.post(
        f'{base}/druid/v2/sql',
        json={
            'query': query,
            'parameters': [{'type': 'VARCHAR', 'value': p} for p in parameters],
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _served_version(base: str, datasource: str) -> Tuple[str, int]:
    '''The newest version among published, unovershadowed segments, and how many
    of those segments are not loaded yet. (0.23 SQL has no MAX over strings.)'''
    rows = _sql(
        base,
        'SELECT "version", is_available FROM sys.segments '
        'WHERE "datasource" = ? AND is_published = 1 AND is_overshadowed = 0',
        datasource,
    )
    newest = max((row['version'] for row in rows), default='')
    return newest, sum(1 for row in rows if not row['is_available'])


def _run_index_task(base: str, datasource: str, task: dict) -> None:
    before, _ = _served_version(base, datasource)
    response = requests.post(f'{base}/druid/indexer/v1/task', json=task, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(
            f'task rejected {response.status_code}: {response.text[:1000]}'
        )
    task_id = response.json()['task']
    print(f'submitted {task_id}')

    def task_done():
        status = requests.get(
            f'{base}/druid/indexer/v1/task/{task_id}/status', timeout=30
        ).json()['status']
        state = status.get('statusCode') or status.get('status')
        if state == 'SUCCESS':
            return state
        if state == 'FAILED':
            raise RuntimeError(f'task {task_id} failed: {status}')
        return None

    _wait(f'task {task_id}', task_done, TASK_TIMEOUT_S)

    # Served means: the task's segments are the newest published version, none of
    # them is overshadowed, and every one is loaded on a historical. Load status
    # alone already reads 100% for a datasource that is being replaced.
    def served():
        newest, unavailable = _served_version(base, datasource)
        if newest > before and unavailable == 0:
            return newest
        return None

    version = _wait(f'{datasource} segments to be served', served, TASK_TIMEOUT_S)
    counts = _sql(base, f'SELECT COUNT(*) AS n, SUM("count") AS c FROM "{datasource}"')
    print(f'{datasource} version {version} served: {counts}')


_VALUE_LEAVES = {'selector', 'in', 'bound', 'regex', 'search', 'like'}


def _two_valued(node: Any) -> Any:
    '''Inside a `not`, make every value comparison false rather than unknown on a
    null dimension: `leaf AND NOT dimension IS NULL`. Druid 28+ evaluates native
    filters with three-valued logic, so `not(Sex = F)` drops null-Sex rows that
    legacy Druid kept. On 0.23 the wrapper changes nothing.'''
    if isinstance(node, list):
        return [_two_valued(item) for item in node]
    if not isinstance(node, dict):
        return node
    if node.get('type') in _VALUE_LEAVES and node.get('value', '') is not None:
        is_null = {'type': 'selector', 'dimension': node['dimension'], 'value': None}
        return {'type': 'and', 'fields': [node, {'type': 'not', 'field': is_null}]}
    return {key: _two_valued(value) for key, value in node.items()}


def candidate_filters(node: Any) -> Any:
    '''The builder fixes WP-8a requests from core, applied to a posted query:
    - the "has no value" test is `selector value null`, not `selector value ''`,
      which under SQL-compatible nulls matches only the empty string;
    - a negated filter keeps rows where the dimension is null (`_two_valued`).'''
    if isinstance(node, list):
        return [candidate_filters(item) for item in node]
    if not isinstance(node, dict):
        return node
    if node.get('type') == 'selector' and node.get('value') == '':
        return {**node, 'value': None}
    if node.get('type') == 'not':
        return {**node, 'field': _two_valued(candidate_filters(node['field']))}
    return {key: candidate_filters(value) for key, value in node.items()}


def _broker(port: int, session: requests.Session, candidate: bool):
    url = f'{_router(port)}/druid/v2'

    def answer(query: dict) -> list:
        if candidate:
            query = candidate_filters(query)
        response = session.post(url, json=query, timeout=QUERY_TIMEOUT_S)
        if response.status_code != 200:
            raise RuntimeError(f'Druid {response.status_code}: {response.text[:1000]}')
        return response.json()

    return answer


def replay(port: int, out: Path, names: List[str], candidate: bool) -> None:
    bootstrap()
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    cases = [
        case for case in load_cases() + audit_cases() if not names or case.name in names
    ]
    failures = 0
    for case in cases:
        record: dict
        try:
            exchanges, body = run_case(case, _broker(port, session, candidate))
            record = {
                'druid_query': [query for query, _ in exchanges],
                'druid_response': [rows for _, rows in exchanges],
                'body': body,
            }
        except Exception as error:  # pylint: disable=broad-except
            failures += 1
            record = {'error': f'{type(error).__name__}: {error}'[:4000]}
        (out / f'{case.name}.json').write_text(to_json_text(record), encoding='utf-8')
    print(f'{len(cases)} cases replayed into {out}, {failures} errors')


def _differences(
    left: Any, right: Any, path: str = '$'
) -> Iterator[Tuple[str, Any, Any]]:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right), key=str):
            yield from _differences(
                left.get(key, '<absent>'), right.get(key, '<absent>'), f'{path}.{key}'
            )
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            yield (f'{path}.length', len(left), len(right))
        for index, (a, b) in enumerate(zip(left, right)):
            yield from _differences(a, b, f'{path}[{index}]')
    elif json.dumps(left, allow_nan=True) != json.dumps(right, allow_nan=True):
        yield (path, left, right)


def diff(left_dir: Path, right_dir: Path, limit: int) -> int:
    changed = results_changed = 0
    for left_path in sorted(left_dir.glob('*.json')):
        right_path = right_dir / left_path.name
        left = json.loads(left_path.read_text(encoding='utf-8'))
        right = json.loads(right_path.read_text(encoding='utf-8'))
        if left == right or to_json_text(left) == to_json_text(right):
            continue
        changed += 1
        result_differs = False
        print(f'## {left_path.stem}')
        for part in ('error', 'druid_query', 'druid_response', 'body'):
            found = list(_differences(left.get(part), right.get(part), part))
            if not found:
                continue
            result_differs = result_differs or part != 'druid_query'
            print(f'- {part}: {len(found)} differing values')
            for path, a, b in found[:limit]:
                print(
                    f'    {path}: {json.dumps(a, allow_nan=True)[:160]} -> '
                    f'{json.dumps(b, allow_nan=True)[:160]}'
                )
        results_changed += result_differs
    print(
        f'{changed} cases differ between {left_dir} and {right_dir}; '
        f'{results_changed} in Druid rows, body or error, '
        f'{changed - results_changed} in query text only'
    )
    return changed


PARITY_FIRST_DAY = date(1900, 1, 1)
PARITY_END_DAY = date(2101, 1, 1)


def _day_dimension(name: str, extraction: dict) -> dict:
    return {
        'type': 'extraction',
        'dimension': '__time',
        'outputName': name,
        'extractionFn': extraction,
    }


PARITY_DATASOURCE = 'wp8a_epi_week_parity'


def _parity_days() -> List[date]:
    return [
        PARITY_FIRST_DAY + timedelta(days=offset)
        for offset in range((PARITY_END_DAY - PARITY_FIRST_DAY).days)
    ]


def _index_parity_days(base: str, days: List[date]) -> None:
    exists = requests.get(f'{base}/druid/coordinator/v1/datasources', timeout=30)
    if PARITY_DATASOURCE in exists.json():
        return
    task = {
        'type': 'index_parallel',
        'spec': {
            'dataSchema': {
                'dataSource': PARITY_DATASOURCE,
                'timestampSpec': {'column': 'day', 'format': 'yyyy-MM-dd'},
                'dimensionsSpec': {'dimensions': []},
                'metricsSpec': [{'type': 'count', 'name': 'count'}],
                'granularitySpec': {
                    'segmentGranularity': 'all',
                    'queryGranularity': 'day',
                    'rollup': True,
                    'intervals': [f'{PARITY_FIRST_DAY}/{PARITY_END_DAY}'],
                },
            },
            'ioConfig': {
                'type': 'index_parallel',
                'inputSource': {
                    'type': 'inline',
                    'data': '\n'.join(day.isoformat() for day in days),
                },
                'inputFormat': {'type': 'csv', 'columns': ['day']},
            },
            'tuningConfig': {
                'type': 'index_parallel',
                'partitionsSpec': {'type': 'dynamic'},
            },
        },
    }
    _run_index_task(base, PARITY_DATASOURCE, task)


def parity(port: int, with_js: bool) -> int:
    days = _parity_days()
    _index_parity_days(_router(port), days)
    dimensions = [
        _day_dimension(
            'day', {'type': 'timeFormat', 'format': 'yyyy-MM-dd', 'timeZone': 'UTC'}
        ),
        _day_dimension('native', epi_week_of_year_extraction()),
    ]
    if with_js:
        dimensions.append(
            _day_dimension(
                'js',
                {'type': 'javascript', 'function': WHO_EPI_WEEK_EXTRACTION_FORMULA},
            )
        )
    query = {
        'queryType': 'groupBy',
        'dataSource': PARITY_DATASOURCE,
        'intervals': [f'{PARITY_FIRST_DAY}/{PARITY_END_DAY}'],
        'granularity': 'all',
        'dimensions': dimensions,
        'aggregations': [{'type': 'longSum', 'name': 'rows', 'fieldName': 'count'}],
        'context': {'timeout': QUERY_TIMEOUT_S * 1000},
    }
    response = requests.post(
        f'{_router(port)}/druid/v2', json=query, timeout=QUERY_TIMEOUT_S
    )
    if response.status_code != 200:
        print(f'Druid {response.status_code}: {response.text[:1000]}')
        return 1
    result = {row['event']['day']: row['event'] for row in response.json()}
    mismatches = []
    for day in days:
        event = result.get(day.isoformat())
        expected = js_epi_week_of_year(day)
        if event is None or event['rows'] != 1:
            mismatches.append((day, 'missing or duplicated', event))
        elif event['native'] != expected or (with_js and event['js'] != expected):
            mismatches.append((day, expected, event))
    compared = (
        'native, JavaScript and the Python port'
        if with_js
        else ('native and the Python port')
    )
    print(
        f'{len(days)} days {days[0]}..{days[-1]}, {len(result)} groups; '
        f'{compared}: {len(mismatches)} mismatches'
    )
    for mismatch in mismatches[:20]:
        print(f'    {mismatch}')
    return 1 if mismatches else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    index_parser = commands.add_parser('index')
    index_parser.add_argument('--port', type=int, required=True)
    index_parser.add_argument(
        '--raw',
        action='store_true',
        help="index without the ingest transform that stores '' as null",
    )
    replay_parser = commands.add_parser('replay')
    replay_parser.add_argument('--port', type=int, required=True)
    replay_parser.add_argument('--out', type=Path, required=True)
    replay_parser.add_argument('cases', nargs='*')
    replay_parser.add_argument(
        '--candidate',
        action='store_true',
        help='post queries as the requested builder fixes would build them',
    )
    diff_parser = commands.add_parser('diff')
    diff_parser.add_argument('left', type=Path)
    diff_parser.add_argument('right', type=Path)
    diff_parser.add_argument('--limit', type=int, default=6)
    parity_parser = commands.add_parser('parity')
    parity_parser.add_argument('--port', type=int, required=True)
    parity_parser.add_argument('--js', action='store_true')
    args = parser.parse_args()

    if args.command == 'index':
        bootstrap()
        index(args.port, args.raw)
    elif args.command == 'replay':
        replay(args.port, args.out, args.cases, args.candidate)
    elif args.command == 'parity':
        return parity(args.port, args.js)
    else:
        diff(args.left, args.right, args.limit)
    return 0


if __name__ == '__main__':
    sys.exit(main())
