"""Query-latency baseline for Harmony (WP-1a, SPEC PERF-7).

Replays a fixed set of `/api2/query/*` requests against the perf stack
(scripts/perf/stack.sh) and records, per case, p50 and p95 latency, response
bytes and Druid-side query time. After the query cases it runs dashboards.mjs
(unless --no-dashboards), which loads the reference dashboards of
dashboards.json in headless Chromium and records time to last tile and bytes
transferred; those rows have endpoint `dashboard`.

Paired mode, the default and the PERF-7 check. The stack runs two copies of
the app against the same Druid: the reference (old code, `stack.sh reference
<git ref>`) and the candidate (this checkout). Every case alternates between
them request by request, the reference first in even rounds and the candidate
first in odd ones, so both sides see the same host load. Each case and
dashboard is judged by two ratios of candidate to reference, and fails when
either is over 1.10 and the lower bound of a paired bootstrap of it (rounds
resampled as pairs) is over 1:

- the p95 ratio, candidate p95 over reference p95: PERF-7 as written, and the
  only check that sees a regression confined to the slow tail;
- the paired median ratio, the median over rounds of candidate time over
  reference time in the same round. The load both sides shared cancels in
  each round, so it sees a slowdown of every request that p95 cannot: stalls
  hitting one side and not its pair move single cases' p95 ratios by up to
  30% in an A/A run on a loaded host, enough to hide a 25% regression. A
  slowdown of every request by a factor raises p95 by the same factor.

Each bound's one-sided level is 5% split over both bounds of every case
(Bonferroni), so an A/A run fails about one time in twenty: 3.0% on this
host's real noise and 6.6% under heavy synthetic stalls, as measured by
scripts/perf/probes/level.py (the README gives the table). The report gives
each case's `detects`: the smallest slowdown of every candidate request that
would have failed it. On an A/A run that is what the run could see; a passing
run's claim is only as strong as its largest `detects`.

    scripts/perf/stack.sh up && scripts/perf/stack.sh ui
    scripts/perf/stack.sh reference    # git merge-base HEAD mig/integration
    eval "$(scripts/perf/stack.sh env)"
    uv run --no-project --with requests python scripts/perf/baseline.py --label WP-1b

The reference is the WP's base, the merge base with mig/integration (decision
0011): that is the code the WP's change lands on. `main` is the pre-migration
tree, hundreds of commits behind, so a run against it would charge the WP
with every merged WP's cost or gain. A phase-exit run uses the phase's start
commit on integration instead; the report says when the reference is not the
merge base.

It writes under docs/modernisation/perf/paired/, named
<date>-<reference sha>-vs-<candidate sha>[-<label>]: `.reference.jsonl` and
`.candidate.jsonl` (one PerfSample per case), `.rounds.jsonl` (every timed
request's latency, per case and side, in round order), `.meta.json` (hardware,
host load at start and end, versions, dataset, method) and `.md` (the paired
verdicts, then both sides' absolute numbers). The absolute numbers are
evidence only: on a shared host they move with its load, and the ratio does
not.

Each request goes out on a new connection (`Connection: close`): while one side
answers, the other side's idle keep-alive connection can pass gunicorn's 2 s
keep-alive and be closed under the next request.

Committed mode (`--committed`, or `--compare [BASE]`) measures the candidate
alone and writes <date>-<git sha>[-<label>] `.jsonl`, `.meta.json` and `.md`
directly under docs/modernisation/perf/. `--compare` then holds each p95 to
10% above BASE's (default: the newest `.jsonl` there), as does

    uv run --no-project python scripts/perf/baseline.py compare BASE.jsonl NEW.jsonl

Absolute numbers only agree from run to run on a quiet, dedicated host, so
this mode is for such a machine.

The cases are WP-2a golden request bodies (tests/golden/cases), sent as the
frontend sends them, with every INTERVAL filter widened to the dataset's three
years so each query reads real volumes. The raw download (table_disaggregated)
gets the dataset's last month instead: over three years it returns 39 MB in
about 140 s a request, which would make one run take well over an hour.

Requests run one at a time from one client, after warm-up rounds, so Druid's
and the app's caches are warm: the numbers are steady-state latency for a
repeated query, not cold-start latency.

A case gets 100 timed requests per side and a dashboard 30 loads. Of 100
requests, p95 lies between the fifth- and sixth-slowest; of 30, between the
second- and third-slowest, so two stalls would set it.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
import os
import platform
import random
import re
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, TypeVar

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DASHBOARD_SCRIPT = HERE / 'dashboards.mjs'
DASHBOARD_SPECS = HERE / 'dashboards.json'
GOLDEN_CASES = REPO_ROOT / 'tests/golden/cases'
RESULTS_DIR = REPO_ROOT / 'docs/modernisation/perf'
SIDES = ('reference', 'candidate')
DATASET_START = '2023-01-01'
DATASET_END = '2026-01-01'
P95_REGRESSION_LIMIT = 0.10
# One-sided error rate of a paired run's verdict, split over both bounds of
# every case (case_alpha).
FAMILY_ALPHA = 0.05
BOOTSTRAP_RESAMPLES = 4000
# Over fewer rounds a bootstrap of p95 resamples little more than the maximum,
# so an A/A case's bound exceeds 1 more often than its level says: at 4 to 10
# rounds two to three times as often (probes/2026-10-06-rounds.txt). Decision
# 0011 sets the floor at 30.
MIN_PAIRED_ROUNDS = 30
REQUEST_LOG_SETTLE_SECONDS = 0.05
# A WP's reference is its merge base with this branch (decision 0011).
BASE_BRANCH = 'mig/integration'

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


T = TypeVar('T')


def interleaved_order(round_index: int, sides: tuple[str, ...]) -> tuple[str, ...]:
    """The order of the sides in one round: as given in even rounds, reversed
    in odd ones, so neither side always runs right after the other."""
    return sides if round_index % 2 == 0 else tuple(reversed(sides))


def run_interleaved(
    sides: tuple[str, ...], rounds: int, warmup: int, measure: Callable[[str], T]
) -> dict[str, list[T]]:
    """Call measure(side) for every side in every round, warm-up rounds first,
    and return each side's results from the timed rounds."""
    results: dict[str, list[T]] = {side: [] for side in sides}
    for index in range(warmup + rounds):
        for side in interleaved_order(index, sides):
            result = measure(side)
            if index >= warmup:
                results[side].append(result)
    return results


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


def case_alpha(cases: int) -> float:
    """The level of each one-sided bound. A case has two bounds (p95 and
    paired median) and either can fail it, so the family budget is split over
    twice the cases: an A/A run then fails any bound about FAMILY_ALPHA of
    the time (Bonferroni)."""
    return FAMILY_ALPHA / (2 * cases)


def beyond_limit(point: float, lower: float) -> bool:
    """A ratio over the PERF-7 limit whose lower confidence bound is over 1."""
    return point > 1 + P95_REGRESSION_LIMIT and lower > 1


@dataclasses.dataclass(frozen=True)
class PairedResult:
    """One case of a paired run, judged by two ratios of candidate to
    reference, each with the lower confidence bound of a bootstrap over rounds:

    - `ratio`, candidate p95 over reference p95: PERF-7 itself, and the only
      check that sees a regression in the slow tail alone;
    - `shift`, the median over rounds of candidate time over reference time in
      the same round: the shared load cancels in each round, so it sees a
      slowdown of every request through noise that hides it from p95. A
      slowdown of every request by a factor raises p95 by that factor too."""

    case_id: str
    reference_p95: float
    candidate_p95: float
    ratio: float
    lower: float
    shift: float
    shift_lower: float

    @property
    def p95_regressed(self) -> bool:
        return beyond_limit(self.ratio, self.lower)

    @property
    def shift_regressed(self) -> bool:
        return beyond_limit(self.shift, self.shift_lower)

    @property
    def regressed(self) -> bool:
        return self.p95_regressed or self.shift_regressed

    @property
    def detects(self) -> float:
        """The smallest factor by which slowing every candidate request would
        fail this case. Both ratios and their bounds scale with the candidate,
        so this is exact; on an A/A run it is the slowdown the run could see."""
        limit = 1 + P95_REGRESSION_LIMIT
        return min(
            max(limit / self.ratio, 1 / self.lower),
            max(limit / self.shift, 1 / self.shift_lower),
        )


def paired_result(
    case_id: str,
    reference_ms: list[float],
    candidate_ms: list[float],
    alpha: float,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> PairedResult:
    """Both ratios of PairedResult, with the alpha quantile of each over
    `resamples` resamplings of the rounds. Rounds are resampled as pairs,
    which keeps the load the two sides shared in a round together. Seeded by
    the case, so a run's files always give the same verdict."""
    if len(reference_ms) != len(candidate_ms):
        raise ValueError(f'{case_id}: sides have different round counts')
    if len(reference_ms) < MIN_PAIRED_ROUNDS:
        raise ValueError(
            f'{case_id}: a paired verdict needs at least {MIN_PAIRED_ROUNDS} rounds'
        )
    n = len(reference_ms)
    per_round = [c / r for r, c in zip(reference_ms, candidate_ms)]
    reference_p95 = percentile(reference_ms, 0.95)
    candidate_p95 = percentile(candidate_ms, 0.95)
    # Seeded so a run's files always give the same verdict; not a secret.
    rng = random.Random(f'{case_id}:{n}')  # noqa: S311
    ratios, shifts = [], []
    for _ in range(resamples):
        rounds = [rng.randrange(n) for _ in range(n)]
        ratios.append(
            percentile([candidate_ms[i] for i in rounds], 0.95)
            / percentile([reference_ms[i] for i in rounds], 0.95)
        )
        shifts.append(percentile([per_round[i] for i in rounds], 0.5))
    return PairedResult(
        case_id,
        reference_p95,
        candidate_p95,
        candidate_p95 / reference_p95,
        percentile(ratios, alpha),
        percentile(per_round, 0.5),
        percentile(shifts, alpha),
    )


def paired_verdict(result: PairedResult) -> str:
    failed = [
        name
        for name, flagged in (
            ('p95', result.p95_regressed),
            ('paired median', result.shift_regressed),
        )
        if flagged
    ]
    if failed:
        return f'REGRESSED ({", ".join(failed)})'
    if max(result.ratio, result.shift) > 1 + P95_REGRESSION_LIMIT:
        return 'over the limit, within noise'
    return 'ok'


def paired_table(results: list[PairedResult]) -> str:
    rows = [
        (
            '| case | reference p95 ms | candidate p95 ms | p95 ratio | lower bound '
            '| paired median ratio | lower bound | detects | verdict |'
        ),
        '|---|---:|---:|---:|---:|---:|---:|---:|---|',
    ]
    for r in results:
        rows.append(
            f'| {r.case_id} | {r.reference_p95:.1f} | {r.candidate_p95:.1f} '
            f'| {r.ratio:.3f} | {r.lower:.3f} | {r.shift:.3f} | {r.shift_lower:.3f} '
            f'| {r.detects:.3f} | {paired_verdict(r)} |'
        )
    return '\n'.join(rows)


def dashboard_samples_by_side(
    lines: Iterable[str],
) -> dict[str, list[tuple[PerfSample, list[float]]]]:
    """Summarise dashboards.mjs output, one JSON line per dashboard and target,
    keeping each load's time in round order."""
    grouped: dict[str, list[tuple[PerfSample, list[float]]]] = {}
    for line in lines:
        if line.strip():
            record = json.loads(line)
            grouped.setdefault(record['target'], []).append(
                (summarise_dashboard(record), record['latencies_ms'])
            )
    return grouped


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


def comparison_table(
    results: list[Comparison], base: str = 'base', new: str = 'new'
) -> str:
    rows = [
        f'| case | {base} p95 ms | {new} p95 ms | change | verdict |',
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
    return verdict(results)


def verdict(results: list[Comparison]) -> int:
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


@dataclasses.dataclass(frozen=True)
class Target:
    """One copy of the app: its side, API and browser URLs and a logged-in session."""

    side: str
    url: str
    ui_url: str
    session: Any


def measure_case(
    targets: list[Target], request_log, case_id, rounds, warmup
) -> dict[str, tuple[PerfSample, list[float]]]:
    """Time one case on every target, interleaved; return each side's sample
    and its latencies in round order.

    Requests run one at a time, so the broker's request-log lines since the
    last drain belong to the request just made, whichever side made it."""
    endpoint, body = load_case(case_id)
    payload = json.dumps(body)
    headers = {'Content-Type': 'application/json', 'Connection': 'close'}
    by_side = {t.side: t for t in targets}

    def request(side: str) -> tuple[float, int, tuple[float, int] | None]:
        target = by_side[side]
        if request_log:
            request_log.drain()
        started = time.perf_counter()
        response = target.session.post(
            f'{target.url}/api2/query/{endpoint}',
            data=payload,
            headers=headers,
            timeout=600,
        )
        content = response.content
        elapsed_ms = (time.perf_counter() - started) * 1000
        if response.status_code != 200:
            raise RuntimeError(
                f'{case_id} ({side}): HTTP {response.status_code}: {content[:500]!r}'
            )
        druid = None
        if request_log:
            # The broker logs a query after streaming its result, so give the
            # line a moment to land; this wait is outside the timed window.
            time.sleep(REQUEST_LOG_SETTLE_SECONDS)
            times = list(druid_times(request_log.drain()))
            druid = (sum(times), len(times))
        return elapsed_ms, len(content), druid

    results = run_interleaved(tuple(by_side), rounds, warmup, request)
    return {
        side: (
            summarise(
                case_id,
                endpoint,
                [ms for ms, _, _ in measured],
                [size for _, size, _ in measured],
                [d for _, _, d in measured if d is not None] if request_log else None,
            ),
            [ms for ms, _, _ in measured],
        )
        for side, measured in results.items()
    }


def git(*args: str) -> str:
    return subprocess.run(
        ['git', *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def http_json(url: str) -> Any:
    import requests

    return requests.get(url, timeout=30).json()


def measure_dashboards(
    targets: list[Target], slugs: list[str], rounds: int, warmup: int
) -> dict[str, list[tuple[PerfSample, list[float]]]]:
    if not slugs:
        return {}
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
    for target in targets:
        command += ['--target', f'{target.side}={target.ui_url}']
    # stderr (progress) passes through; stdout is one JSON line per dashboard
    # and target.
    output = subprocess.run(
        command, stdout=subprocess.PIPE, text=True, check=True
    ).stdout
    return dashboard_samples_by_side(output.splitlines())


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


def refuse_existing(stem: Path) -> None:
    """Exit when any file of this run's stem is already written. A failing run
    stays beside its rerun (decision 0011, item 4), so a rerun on the same
    day, commits and label must take a new label rather than replace it."""
    existing = sorted(stem.parent.glob(f'{stem.name}.*'))
    if existing:
        names = ', '.join(path.name for path in existing)
        raise SystemExit(
            f'refusing to overwrite a recorded run ({names}); '
            'pick a new --label, e.g. WP-<id>-rerun1'
        )


def write_results(stem: Path, samples: list[PerfSample], meta: dict[str, Any]) -> None:
    refuse_existing(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix('.jsonl').write_text(
        ''.join(json.dumps(dataclasses.asdict(s)) + '\n' for s in samples)
    )
    stem.with_suffix('.meta.json').write_text(json.dumps(meta, indent=2) + '\n')
    stem.with_suffix('.md').write_text(markdown(stem.name, samples, meta))


def markdown(title: str, samples: list[PerfSample], meta: dict[str, Any]) -> str:
    return (
        '\n'.join(
            [
                f'# Performance baseline {title}',
                '',
                *method_lines(meta),
                '',
                *sample_table(samples),
            ]
        )
        + '\n'
    )


def method_lines(meta: dict[str, Any]) -> list[str]:
    host = meta['host']
    method = meta['method']
    end = host.get('load_average_at_end')
    end_load = f', {end} at end' if end else ''
    dirty = ' (dirty)' if meta['git_dirty'] else ''
    if 'reference_sha' in meta:
        code = (
            f'- Code: reference `{meta["reference_sha"]}`, candidate '
            f'`{meta["candidate_sha"]}`{dirty}, run {meta["started_utc"]}'
        )
    else:
        code = f'- Code: `{meta["git_sha"]}`{dirty}, run {meta["started_utc"]}'
    lines = [
        code,
        (
            f'- Host: {host["cpu"]}, {host["logical_cpus"]} logical CPUs, {host["memory_gib"]} GiB, '
            f'Linux {host["kernel"]}, load {host["load_average_at_start"]} at start'
            f'{end_load}; '
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
    if 'pairing' in method:
        lines.append(f'- Pairing: {method["pairing"]}')
    if 'reference_sha' in meta and meta.get('integration_merge_base'):
        lines.append(reference_line(meta))
    if 'dataset' in meta:
        lines.append(f'- Dataset: {meta["dataset"]}')
    return lines


def reference_line(meta: dict[str, Any]) -> str:
    base = meta['integration_merge_base']
    if meta['reference_sha'] == base:
        return f"- Reference: the WP's base (merge base with {BASE_BRANCH})"
    return (
        f'- Reference: not the merge base with {BASE_BRANCH} (`{base}`); '
        'only a phase-exit run, against the phase start, uses another commit'
    )


def integration_merge_base() -> str | None:
    try:
        return git('merge-base', 'HEAD', BASE_BRANCH)
    except subprocess.CalledProcessError:
        return None


def sample_table(samples: list[PerfSample]) -> list[str]:
    lines = [
        '| case | endpoint | p50 ms | p95 ms | min ms | max ms | bytes | Druid ms | Druid queries |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for s in samples:
        lines.append(
            f'| {s.case_id} | {s.endpoint} | {s.p50_ms} | {s.p95_ms} | {s.min_ms} | {s.max_ms} '
            f'| {s.bytes} | {s.druid_ms if s.druid_ms is not None else "n/a"} '
            f'| {s.druid_queries if s.druid_queries is not None else "n/a"} |'
        )
    return lines


def paired_stem(
    out: Path, date: str, reference_sha: str, candidate_sha: str, label: str
) -> Path:
    suffix = f'-{label}' if label else ''
    return (
        out / 'paired' / f'{date}-{reference_sha[:10]}-vs-{candidate_sha[:10]}{suffix}'
    )


def finish_paired(
    stem: Path,
    reference: list[PerfSample],
    candidate: list[PerfSample],
    rounds: dict[str, tuple[list[float], list[float]]],
    meta: dict[str, Any],
) -> int:
    """Write a paired run's files, print the verdicts, return the exit code."""
    refuse_existing(stem)
    alpha = case_alpha(len(rounds))
    results = [
        paired_result(case_id, reference_ms, candidate_ms, alpha)
        for case_id, (reference_ms, candidate_ms) in rounds.items()
    ]
    stem.parent.mkdir(parents=True, exist_ok=True)
    for side, samples in (('reference', reference), ('candidate', candidate)):
        Path(f'{stem}.{side}.jsonl').write_text(
            ''.join(json.dumps(dataclasses.asdict(s)) + '\n' for s in samples)
        )
    Path(f'{stem}.rounds.jsonl').write_text(
        ''.join(
            json.dumps({'case_id': c, 'reference_ms': r, 'candidate_ms': n}) + '\n'
            for c, (r, n) in rounds.items()
        )
    )
    Path(f'{stem}.meta.json').write_text(json.dumps(meta, indent=2) + '\n')
    table = paired_table(results)
    heading = (
        f'Candidate over reference; a case regresses when its p95 ratio or its '
        f'paired median ratio is over {1 + P95_REGRESSION_LIMIT:.2f} and that '
        f"ratio's lower bound (one-sided {alpha:.2%}, paired bootstrap of "
        f'{BOOTSTRAP_RESAMPLES} resamples) is over 1. `detects` is the smallest '
        f'slowdown of every candidate request that would have failed the case'
    )
    failed = [r.case_id for r in results if r.regressed]
    sensitivity = (
        f'every case would have failed a slowdown of '
        f'{max(r.detects for r in results):.3f} or more'
    )
    outcome = (
        f'FAIL: {", ".join(failed)}'
        if failed
        else f'OK: no case regressed; {sensitivity}'
    )
    Path(f'{stem}.md').write_text(
        '\n'.join(
            [
                f'# Paired performance run {stem.name}',
                '',
                *method_lines(meta),
                '',
                '## Verdict',
                '',
                heading + '.',
                '',
                table,
                '',
                outcome,
                '',
                '## Reference, absolute (evidence only)',
                '',
                *sample_table(reference),
                '',
                '## Candidate, absolute (evidence only)',
                '',
                *sample_table(candidate),
            ]
        )
        + '\n'
    )
    print(f'wrote {stem}.{{reference,candidate,rounds}}.jsonl, .meta.json and .md')
    print(heading + ':')
    print(table)
    print(outcome)
    return 1 if failed else 0


def run(args: argparse.Namespace) -> int:
    log_dir = os.environ.get('PERF_REQUEST_LOG_DIR')
    request_log = RequestLog(Path(log_dir)) if log_dir else None
    candidate = Target(
        'candidate',
        require_env('PERF_CANDIDATE_URL').rstrip('/'),
        require_env('PERF_CANDIDATE_UI_URL').rstrip('/'),
        None,
    )
    targets = [candidate]
    if args.mode == 'paired':
        reference = Target(
            'reference',
            require_env('PERF_REFERENCE_URL').rstrip('/'),
            require_env('PERF_REFERENCE_UI_URL').rstrip('/'),
            None,
        )
        targets = [reference, candidate]
    targets = [dataclasses.replace(t, session=login(t.url)) for t in targets]
    meta = environment(args.rounds, args.warmup)
    if args.mode == 'paired':
        meta['reference_sha'] = require_env('PERF_REFERENCE_SHA')
        meta['candidate_sha'] = meta.pop('git_sha')
        meta['integration_merge_base'] = integration_merge_base()
        meta['method']['pairing'] = (
            'reference and candidate apps on one host against one Druid; each '
            'round sends the case to both, reference first in even rounds and '
            'candidate first in odd ones; a case regresses when its p95 ratio or '
            'its paired median ratio (median over rounds of candidate over '
            'reference time) is above 1.10 with a paired-bootstrap lower bound '
            'above 1; every request on a new connection'
        )
    if args.dataset:
        meta['dataset'] = args.dataset
    date = dt.datetime.now(dt.timezone.utc).date().isoformat()
    if args.mode == 'paired':
        stem = paired_stem(
            args.out, date, meta['reference_sha'], meta['candidate_sha'], args.label
        )
    else:
        label = f'-{args.label}' if args.label else ''
        stem = args.out / f'{date}-{meta["git_sha"][:10]}{label}'
    refuse_existing(stem)
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
    samples: dict[str, list[PerfSample]] = {t.side: [] for t in targets}
    latencies: dict[str, dict[str, list[float]]] = {t.side: {} for t in targets}
    for name in names:
        for side, (sample, measured) in measure_case(
            targets, request_log, name, args.rounds, args.warmup
        ).items():
            print(
                f'{name:40} {side:9} p50 {sample.p50_ms:8.1f}  p95 {sample.p95_ms:8.1f} ms  '
                f'{sample.bytes:>9} B  druid {sample.druid_ms} ms',
                flush=True,
            )
            samples[side].append(sample)
            latencies[side][name] = measured
    dashboards = measure_dashboards(
        targets, slugs, args.dashboard_rounds, args.dashboard_warmup
    )
    for side, side_samples in dashboards.items():
        for sample, measured in side_samples:
            print(
                f'{sample.case_id:40} {side:9} p50 {sample.p50_ms:8.1f}  p95 {sample.p95_ms:8.1f} ms  '
                f'{sample.bytes:>9} B  (time to last tile)',
                flush=True,
            )
            samples[side].append(sample)
            latencies[side][sample.case_id] = measured
    meta['host']['load_average_at_end'] = [round(x, 2) for x in os.getloadavg()]
    meta['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat(
        timespec='seconds'
    )
    if args.mode == 'paired':
        rounds = {
            case: (measured, latencies['candidate'][case])
            for case, measured in latencies['reference'].items()
        }
        return finish_paired(
            stem, samples['reference'], samples['candidate'], rounds, meta
        )
    base = None
    if args.compare is not None:
        base = Path(args.compare) if args.compare else newest_baseline()
    write_results(stem, samples['candidate'], meta)
    print(f'wrote {stem}.jsonl, .meta.json and .md')
    return report_comparison(base, stem.with_suffix('.jsonl')) if base else 0


def run_label(value: str) -> str:
    """A --label: letters, digits, underscores and hyphens only. The overwrite
    refusal globs `<stem>.*`, so a dot would turn part of a committed-mode
    label into a suffix, and glob characters would match other runs or none."""
    if not re.fullmatch(r'[A-Za-z0-9_-]*', value):
        raise argparse.ArgumentTypeError(
            f'{value!r}: use only letters, digits, underscores and hyphens'
        )
    return value


def parse_args(argv: list[str]) -> argparse.Namespace:
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
    parser.add_argument(
        '--label',
        type=run_label,
        default='',
        help='suffix for the output file names (letters, digits, _ and -)',
    )
    parser.add_argument('--out', type=Path, default=RESULTS_DIR)
    parser.add_argument(
        '--dataset', default='', help='dataset description for the report'
    )
    parser.add_argument(
        '--committed',
        action='store_true',
        help='measure the candidate alone and record a committed baseline '
        '(needs a quiet, dedicated host)',
    )
    parser.add_argument(
        '--compare',
        nargs='?',
        const='',
        default=None,
        metavar='BASE',
        help='committed mode: compare p95 against BASE (default: the newest .jsonl)',
    )
    args = parser.parse_args(argv)
    args.mode = 'committed' if args.committed or args.compare is not None else 'paired'
    if args.mode == 'paired':
        for flag, value in (
            ('--rounds', args.rounds),
            ('--dashboard-rounds', args.dashboard_rounds),
        ):
            if value < MIN_PAIRED_ROUNDS:
                parser.error(
                    f'{flag}: a paired run needs at least {MIN_PAIRED_ROUNDS} rounds'
                )
    return args


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['compare']:
        parser = argparse.ArgumentParser(prog='baseline.py compare')
        parser.add_argument('base', type=Path)
        parser.add_argument('new', type=Path)
        parsed = parser.parse_args(argv[1:])
        return report_comparison(parsed.base, parsed.new)
    return run(parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
