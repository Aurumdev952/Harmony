"""Query-latency baseline for Harmony (WP-1a, SPEC PERF-7).

Replays a fixed set of `/api2/query/*` requests against the perf stack
(scripts/perf/stack.sh) and records, per case, p50 and p95 latency, response
bytes and Druid-side query time:

    eval "$(scripts/perf/stack.sh env)"
    uv run --no-project --with requests python scripts/perf/baseline.py
    uv run --no-project --with requests python scripts/perf/baseline.py --compare
    uv run --no-project python scripts/perf/baseline.py compare BASE.jsonl NEW.jsonl

After the query cases it runs dashboards.mjs (unless --no-dashboards), which
loads the reference dashboards of dashboards.json in headless Chromium and
records time to last tile and bytes transferred; those rows have endpoint
`dashboard`, and their p95 is held to the same limit.

A run writes three files under docs/modernisation/perf/, named
<date>-<git sha>[-<label>]: `.jsonl` (one PerfSample per case), `.meta.json`
(hardware, versions, dataset, method) and `.md` (both, as tables).

`--compare [BASE]` and `compare` fail when any case's p95 is more than 10% above
the base's (PERF-7). Without a path, the base is the newest committed `.jsonl`.

The cases are WP-2a golden request bodies (tests/golden/cases), sent as the
frontend sends them, with every INTERVAL filter widened to the dataset's three
years so each query reads real volumes. The raw download (table_disaggregated)
gets the dataset's last month instead: over three years it returns 39 MB in
about 140 s a request, which would make one run take well over an hour.

Requests run one at a time from one client, after warm-up rounds, so Druid's
and the app's caches are warm: the numbers are steady-state latency for a
repeated query, not cold-start latency.

A case gets 100 timed requests and a dashboard 30 loads. Of 100 requests,
p95 lies between the fifth- and sixth-slowest; of 30, between the second- and
third-slowest, so two stalls on a shared host would set it.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DASHBOARD_SCRIPT = HERE / 'dashboards.mjs'
DASHBOARD_SPECS = HERE / 'dashboards.json'
GOLDEN_CASES = REPO_ROOT / 'tests/golden/cases'
RESULTS_DIR = REPO_ROOT / 'docs/modernisation/perf'
DATASET_START = '2023-01-01'
DATASET_END = '2026-01-01'
P95_REGRESSION_LIMIT = 0.10
REQUEST_LOG_SETTLE_SECONDS = 0.05

# Golden cases replayed, covering every query endpoint the frontend calls. The
# policy cases are left out: they need a second, policy-restricted account.
CASES = (
    'bar_graph_sum_by_state_month',
    'bar_graph_box_plot',
    'bar_graph_histogram',
    'group_granularity_day',
    'line_graph_time_by_state',
    'line_graph_bump_chart_quarter',
    'line_graph_heat_tiles_week',
    'table_by_state_sex_with_total',
    'group_two_totals',
    'calc_formula',
    'calc_count_distinct_by_state',
    'table_disaggregated',
    'map_by_municipality',
    'map_by_state_month',
    'hierarchy_expando_tree',
    'hierarchy_sunburst',
    'dq_data_quality',
    'dq_data_quality_table',
    'dq_field_reporting_stats',
    'dq_outliers_line_graph',
    'dq_reporting_completeness_line_graph',
)

# Cases measured over a narrower interval than the dataset span (see above).
INTERVALS = {'table_disaggregated': ('2025-12-01', DATASET_END)}


@dataclasses.dataclass(frozen=True)
class PerfSample:
    """One case's result; the first six fields are phase-1's `PerfSample`."""

    case_id: str
    endpoint: str
    p50_ms: float
    p95_ms: float
    bytes: int
    druid_ms: float | None
    n: int
    min_ms: float
    max_ms: float
    druid_queries: int | None


def widen_intervals(
    node: Any, start: str = DATASET_START, end: str = DATASET_END
) -> Any:
    """Return a copy of a request body with every INTERVAL filter set to [start, end)."""
    if isinstance(node, list):
        return [widen_intervals(item, start, end) for item in node]
    if not isinstance(node, dict):
        return node
    copy = {key: widen_intervals(value, start, end) for key, value in node.items()}
    if copy.get('type') == 'INTERVAL':
        copy['start'] = start
        copy['end'] = end
    return copy


def case_interval(name: str) -> tuple[str, str]:
    return INTERVALS.get(name, (DATASET_START, DATASET_END))


def load_case(name: str) -> tuple[str, dict[str, Any]]:
    case_dir = GOLDEN_CASES / name
    endpoint = json.loads((case_dir / 'case.json').read_text())['endpoint']
    body = json.loads((case_dir / 'request.json').read_text())
    return endpoint, widen_intervals(body, *case_interval(name))


def percentile(values: Iterable[float], fraction: float) -> float:
    """Linear interpolation between closest ranks (NumPy's default method)."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError('percentile of no values')
    rank = fraction * (len(ordered) - 1)
    low = math.floor(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarise(
    case_id: str,
    endpoint: str,
    latencies_ms: list[float],
    body_bytes: list[int],
    druid: list[tuple[float, int]] | None,
) -> PerfSample:
    if len(set(body_bytes)) > 1:
        raise RuntimeError(
            f'{case_id}: response size changed between rounds: {body_bytes}'
        )
    return PerfSample(
        case_id=case_id,
        endpoint=endpoint,
        p50_ms=round(percentile(latencies_ms, 0.5), 1),
        p95_ms=round(percentile(latencies_ms, 0.95), 1),
        bytes=body_bytes[0],
        druid_ms=round(statistics.median(ms for ms, _ in druid), 1) if druid else None,
        n=len(latencies_ms),
        min_ms=round(min(latencies_ms), 1),
        max_ms=round(max(latencies_ms), 1),
        druid_queries=max(count for _, count in druid) if druid else None,
    )


def summarise_dashboard(record: dict[str, Any]) -> PerfSample:
    """Summarise one dashboards.mjs line. Bytes are the median: a load counts
    what arrived before its last tile rendered, which can include a font or
    not."""
    case_id = record['case_id']
    if len(set(record['query_requests'])) > 1:
        raise RuntimeError(
            f'{case_id}: query requests changed between loads: {record["query_requests"]}'
        )
    latencies = record['latencies_ms']
    return PerfSample(
        case_id=case_id,
        endpoint='dashboard',
        p50_ms=round(percentile(latencies, 0.5), 1),
        p95_ms=round(percentile(latencies, 0.95), 1),
        bytes=int(statistics.median(record['bytes'])),
        druid_ms=None,
        n=len(latencies),
        min_ms=round(min(latencies), 1),
        max_ms=round(max(latencies), 1),
        druid_queries=None,
    )


def dashboard_slugs() -> list[str]:
    return list(json.loads(DASHBOARD_SPECS.read_text()))


def split_cases(names: list[str] | None) -> tuple[list[str], list[str]]:
    """Split --case names into query cases and dashboard slugs (all of both by default)."""
    slugs = dashboard_slugs()
    if not names:
        return list(CASES), slugs
    return [n for n in names if n not in slugs], [n for n in names if n in slugs]


def druid_times(lines: Iterable[str]) -> Iterator[float]:
    """Yield `query/time` from broker request-log lines (`ts, remote, query, stats`)."""
    for line in lines:
        fields = line.rstrip('\n').split('\t')
        if len(fields) < 4:
            continue
        stats = json.loads(fields[-1])
        if 'query/time' in stats:
            yield float(stats['query/time'])


class RequestLog:
    """Reads what the broker appended to its request log since the last call."""

    def __init__(self, directory: Path):
        self._directory = directory
        self._offsets: dict[Path, int] = {}
        self.drain()

    def drain(self) -> list[str]:
        lines: list[str] = []
        for path in sorted(self._directory.glob('*.log')):
            with path.open('rb') as handle:
                handle.seek(self._offsets.get(path, 0))
                data = handle.read()
            complete = data[: data.rfind(b'\n') + 1]
            self._offsets[path] = self._offsets.get(path, 0) + len(complete)
            lines.extend(complete.decode('utf-8').splitlines())
        return lines


@dataclasses.dataclass(frozen=True)
class Comparison:
    case_id: str
    base_p95: float | None
    new_p95: float | None

    @property
    def ratio(self) -> float | None:
        if self.base_p95 is None or self.new_p95 is None or self.base_p95 == 0:
            return None
        return self.new_p95 / self.base_p95

    @property
    def regressed(self) -> bool:
        ratio = self.ratio
        return ratio is not None and ratio > 1 + P95_REGRESSION_LIMIT

    @property
    def missing(self) -> bool:
        """A base case the new run lost. Cases only the new run has are not failures."""
        return self.base_p95 is not None and self.new_p95 is None


def compare(base: list[PerfSample], new: list[PerfSample]) -> list[Comparison]:
    base_by_id = {s.case_id: s.p95_ms for s in base}
    new_by_id = {s.case_id: s.p95_ms for s in new}
    ids = list(base_by_id) + [i for i in new_by_id if i not in base_by_id]
    return [Comparison(i, base_by_id.get(i), new_by_id.get(i)) for i in ids]


def read_samples(path: Path) -> list[PerfSample]:
    fields = {f.name for f in dataclasses.fields(PerfSample)}
    return [
        PerfSample(**{k: v for k, v in json.loads(line).items() if k in fields})
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def comparison_table(results: list[Comparison]) -> str:
    rows = [
        '| case | base p95 ms | new p95 ms | change | verdict |',
        '|---|---:|---:|---:|---|',
    ]
    for c in results:
        change = f'{(c.ratio - 1) * 100:+.1f}%' if c.ratio is not None else 'n/a'
        if c.missing:
            verdict = 'missing'
        elif c.base_p95 is None:
            verdict = 'new case'
        else:
            verdict = 'REGRESSED' if c.regressed else 'ok'
        rows.append(
            f'| {c.case_id} | {c.base_p95} | {c.new_p95} | {change} | {verdict} |'
        )
    return '\n'.join(rows)


def report_comparison(base_path: Path, new_path: Path) -> int:
    results = compare(read_samples(base_path), read_samples(new_path))
    print(
        f'p95 of {new_path.name} against {base_path.name} (limit +{P95_REGRESSION_LIMIT:.0%}):'
    )
    print(comparison_table(results))
    failed = [c.case_id for c in results if c.regressed or c.missing]
    if failed:
        print(f'FAIL: {", ".join(failed)}')
        return 1
    print('OK: no case regressed')
    return 0


def newest_baseline(exclude: Path | None = None) -> Path:
    candidates = sorted(p for p in RESULTS_DIR.glob('*.jsonl') if p != exclude)
    if not candidates:
        raise FileNotFoundError(f'no baseline .jsonl in {RESULTS_DIR}')
    return candidates[-1]


# --- running against the stack -------------------------------------------------


def read_secret(path: Path, name: str) -> str:
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o600:
        raise PermissionError(f'{path} must be owned by you with mode 600')
    for line in path.read_text().splitlines():
        key, _, value = line.partition('=')
        if key == name:
            return value
    raise LookupError(f'{name} not in {path}')


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f'{name} is not set: run eval "$(scripts/perf/stack.sh env)"')
    return value


def login(base_url: str):
    import requests

    session = requests.Session()
    password = read_secret(Path(require_env('PERF_CREDENTIALS_FILE')), 'PERF_PASSWORD')
    response = session.post(
        f'{base_url}/api2/authentication/login',
        params={'set_cookie': 'true'},
        json={'email': require_env('PERF_USERNAME'), 'password': password},
        timeout=60,
    )
    response.raise_for_status()
    return session


def measure_case(session, base_url, request_log, case_id, rounds, warmup) -> PerfSample:
    endpoint, body = load_case(case_id)
    url = f'{base_url}/api2/query/{endpoint}'
    payload = json.dumps(body)
    headers = {'Content-Type': 'application/json'}
    latencies: list[float] = []
    sizes: list[int] = []
    druid: list[tuple[float, int]] = []
    for index in range(warmup + rounds):
        if request_log:
            request_log.drain()
        started = time.perf_counter()
        response = session.post(url, data=payload, headers=headers, timeout=600)
        content = response.content
        elapsed_ms = (time.perf_counter() - started) * 1000
        if response.status_code != 200:
            raise RuntimeError(
                f'{case_id}: HTTP {response.status_code}: {content[:500]!r}'
            )
        if index < warmup:
            continue
        latencies.append(elapsed_ms)
        sizes.append(len(content))
        if request_log:
            # The broker logs a query after streaming its result, so give the
            # line a moment to land; this wait is outside the timed window.
            time.sleep(REQUEST_LOG_SETTLE_SECONDS)
            times = list(druid_times(request_log.drain()))
            druid.append((sum(times), len(times)))
    return summarise(
        case_id, endpoint, latencies, sizes, druid if request_log else None
    )


def git(*args: str) -> str:
    return subprocess.run(
        ['git', *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def http_json(url: str) -> Any:
    import requests

    return requests.get(url, timeout=30).json()


def measure_dashboards(slugs: list[str], rounds: int, warmup: int) -> list[PerfSample]:
    command = [
        'node',
        str(DASHBOARD_SCRIPT),
        '--rounds',
        str(rounds),
        '--warmup',
        str(warmup),
    ]
    for slug in slugs:
        command += ['--dashboard', slug]
    # stderr (progress) passes through; stdout is one JSON line per dashboard.
    output = subprocess.run(
        command, stdout=subprocess.PIPE, text=True, check=True
    ).stdout
    return [
        summarise_dashboard(json.loads(line)) for line in output.splitlines() if line
    ]


def environment(rounds: int, warmup: int) -> dict[str, Any]:
    cpu = next(
        (
            line.split(':', 1)[1].strip()
            for line in Path('/proc/cpuinfo').read_text().splitlines()
            if line.startswith('model name')
        ),
        platform.processor(),
    )
    mem_kib = int(Path('/proc/meminfo').read_text().split()[1])
    meta: dict[str, Any] = {
        'git_sha': git('rev-parse', 'HEAD'),
        'git_dirty': bool(git('status', '--porcelain', '--untracked-files=no')),
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
        'host': {
            'cpu': cpu,
            'logical_cpus': os.cpu_count(),
            'memory_gib': round(mem_kib / 1024 / 1024, 1),
            'kernel': platform.release(),
            'load_average_at_start': [round(x, 2) for x in os.getloadavg()],
        },
        'method': {
            'rounds': rounds,
            'warmup_rounds': warmup,
            'concurrency': 1,
            'interval': f'{DATASET_START}/{DATASET_END}',
            'interval_overrides': {
                name: '/'.join(span) for name, span in INTERVALS.items()
            },
            'caches': 'warm (Druid broker and historical caches on, as druid_setup ships them)',
            'percentiles': 'linear interpolation between closest ranks',
            'druid_ms': 'median over rounds of the summed broker query/time per request',
        },
    }
    docker = subprocess.run(
        ['docker', 'version', '--format', '{{.Server.Version}}'],
        capture_output=True,
        text=True,
        check=False,
    )
    meta['docker'] = docker.stdout.strip() or None
    coordinator = os.environ.get('PERF_COORDINATOR_URL')
    broker = os.environ.get('PERF_BROKER_URL')
    if coordinator and broker:
        meta['druid_version'] = http_json(f'{coordinator}/status')['version']
        datasources = sorted(http_json(f'{broker}/druid/v2/datasources'))
        meta['datasources'] = datasources
    return meta


def write_results(stem: Path, samples: list[PerfSample], meta: dict[str, Any]) -> None:
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix('.jsonl').write_text(
        ''.join(json.dumps(dataclasses.asdict(s)) + '\n' for s in samples)
    )
    stem.with_suffix('.meta.json').write_text(json.dumps(meta, indent=2) + '\n')
    stem.with_suffix('.md').write_text(markdown(stem.name, samples, meta))


def markdown(title: str, samples: list[PerfSample], meta: dict[str, Any]) -> str:
    host = meta['host']
    method = meta['method']
    lines = [
        f'# Performance baseline {title}',
        '',
        f'- Code: `{meta["git_sha"]}`{" (dirty)" if meta["git_dirty"] else ""}, run {meta["started_utc"]}',
        (
            f'- Host: {host["cpu"]}, {host["logical_cpus"]} logical CPUs, {host["memory_gib"]} GiB, '
            f'Linux {host["kernel"]}, load {host["load_average_at_start"]} at start; '
            f'Docker {meta.get("docker")}'
        ),
        f'- Druid {meta.get("druid_version")}, datasource {", ".join(meta.get("datasources", []))}',
        (
            f'- Method: {method["rounds"]} timed rounds after {method["warmup_rounds"]} warm-up, '
            f'concurrency {method["concurrency"]}, intervals widened to {method["interval"]}, '
            f'caches {method["caches"]}'
        ),
    ]
    overrides = method.get('interval_overrides') or {}
    if overrides:
        spans = ', '.join(f'{name} {span}' for name, span in overrides.items())
        lines.append(f'- Narrower intervals: {spans}')
    dashboards = method.get('dashboards')
    if dashboards:
        lines.append(
            f'- Dashboards (endpoint `dashboard`, time to last tile): '
            f'{dashboards["rounds"]} loads after {dashboards["warmup_rounds"]} warm-up, '
            f'{dashboards["view"]}; ends at the {dashboards["end"]}; bytes are the '
            f'{dashboards["bytes"]}'
        )
    if 'dataset' in meta:
        lines.append(f'- Dataset: {meta["dataset"]}')
    lines += [
        '',
        '| case | endpoint | p50 ms | p95 ms | min ms | max ms | bytes | Druid ms | Druid queries |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for s in samples:
        lines.append(
            f'| {s.case_id} | {s.endpoint} | {s.p50_ms} | {s.p95_ms} | {s.min_ms} | {s.max_ms} '
            f'| {s.bytes} | {s.druid_ms if s.druid_ms is not None else "n/a"} '
            f'| {s.druid_queries if s.druid_queries is not None else "n/a"} |'
        )
    return '\n'.join(lines) + '\n'


def run(args: argparse.Namespace) -> int:
    base_url = require_env('PERF_BASE_URL').rstrip('/')
    log_dir = os.environ.get('PERF_REQUEST_LOG_DIR')
    request_log = RequestLog(Path(log_dir)) if log_dir else None
    session = login(base_url)
    meta = environment(args.rounds, args.warmup)
    if args.dataset:
        meta['dataset'] = args.dataset
    names, slugs = split_cases(args.case)
    if args.no_dashboards:
        slugs = []
    else:
        meta['method']['dashboards'] = {
            'rounds': args.dashboard_rounds,
            'warmup_rounds': args.dashboard_warmup,
            'view': '?screenshot=1 at 1440x900, fresh browser context per load, '
            'requests leaving the stack aborted',
            'end': 'first frame with every query tile rendered',
            'bytes': 'median of headers plus encoded bodies received before the last tile',
        }
    samples = []
    for name in names:
        sample = measure_case(
            session, base_url, request_log, name, args.rounds, args.warmup
        )
        print(
            f'{name:40} p50 {sample.p50_ms:8.1f}  p95 {sample.p95_ms:8.1f} ms  '
            f'{sample.bytes:>9} B  druid {sample.druid_ms} ms',
            flush=True,
        )
        samples.append(sample)
    for sample in measure_dashboards(
        slugs, args.dashboard_rounds, args.dashboard_warmup
    ):
        print(
            f'{sample.case_id:40} p50 {sample.p50_ms:8.1f}  p95 {sample.p95_ms:8.1f} ms  '
            f'{sample.bytes:>9} B  (time to last tile)',
            flush=True,
        )
        samples.append(sample)
    meta['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat(
        timespec='seconds'
    )
    label = f'-{args.label}' if args.label else ''
    stem = (
        args.out
        / f'{dt.datetime.now(dt.timezone.utc).date().isoformat()}-{meta["git_sha"][:10]}{label}'
    )
    base = None
    if args.compare is not None:
        base = Path(args.compare) if args.compare else newest_baseline()
    write_results(stem, samples, meta)
    print(f'wrote {stem}.jsonl, .meta.json and .md')
    return report_comparison(base, stem.with_suffix('.jsonl')) if base else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['compare']:
        parser = argparse.ArgumentParser(prog='baseline.py compare')
        parser.add_argument('base', type=Path)
        parser.add_argument('new', type=Path)
        parsed = parser.parse_args(argv[1:])
        return report_comparison(parsed.base, parsed.new)
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--rounds', type=int, default=100)
    parser.add_argument('--warmup', type=int, default=3)
    parser.add_argument(
        '--case',
        action='append',
        help='run only these cases (query case or dashboard slug)',
    )
    parser.add_argument(
        '--no-dashboards', action='store_true', help='skip dashboards.mjs'
    )
    parser.add_argument('--dashboard-rounds', type=int, default=30)
    parser.add_argument('--dashboard-warmup', type=int, default=2)
    parser.add_argument('--label', default='', help='suffix for the output file names')
    parser.add_argument('--out', type=Path, default=RESULTS_DIR)
    parser.add_argument(
        '--dataset', default='', help='dataset description for the report'
    )
    parser.add_argument(
        '--compare',
        nargs='?',
        const='',
        default=None,
        metavar='BASE',
        help='compare p95 against BASE (default: the newest committed .jsonl)',
    )
    return run(parser.parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
