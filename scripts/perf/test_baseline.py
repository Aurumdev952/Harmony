"""Tests for the offline parts of baseline.py: statistics, case loading, the
request-log reader and the PERF-7 comparison.

    uv run --no-project --with pytest --with hypothesis python -m pytest scripts/perf
"""

from __future__ import annotations

import json
import math
import random
import statistics
from pathlib import Path

import baseline
import pytest
from baseline import PerfSample
from hypothesis import given
from hypothesis import strategies as st

latencies = st.lists(
    st.floats(min_value=0.1, max_value=1e5, allow_nan=False), min_size=1, max_size=60
)


def sample(case_id: str, p95: float) -> PerfSample:
    return PerfSample(case_id, 'table', p95 / 2, p95, 100, 1.0, 30, 1.0, p95, 1)


@given(latencies, st.floats(min_value=0, max_value=1))
def test_percentile_lies_between_min_and_max(values, fraction):
    assert min(values) <= baseline.percentile(values, fraction) <= max(values)


@given(latencies)
def test_percentile_is_monotonic_in_the_fraction(values):
    points = [baseline.percentile(values, f / 20) for f in range(21)]
    assert points == sorted(points)


@given(latencies)
def test_median_matches_the_statistics_module(values):
    assert math.isclose(
        baseline.percentile(values, 0.5), statistics.median(values), rel_tol=1e-9
    )


def test_p95_of_twenty_values_interpolates_between_the_top_two():
    assert baseline.percentile(range(1, 21), 0.95) == pytest.approx(19.05)


def test_every_case_loads_with_intervals_widened_and_nothing_else_changed():
    for name in baseline.CASES:
        endpoint, body = baseline.load_case(name)
        original = json.loads(
            (baseline.GOLDEN_CASES / name / 'request.json').read_text()
        )
        assert endpoint, name
        intervals = list(_intervals(body))
        assert intervals, f'{name} has no INTERVAL filter to widen'
        expected = baseline.case_interval(name)
        assert all((i['start'], i['end']) == expected for i in intervals), name
        assert _without_dates(body) == _without_dates(original), name


def test_cases_span_the_dataset_except_the_raw_download():
    spans = {name: baseline.case_interval(name) for name in baseline.CASES}
    assert spans.pop('table_disaggregated') == ('2025-12-01', '2026-01-01')
    assert set(spans.values()) == {(baseline.DATASET_START, baseline.DATASET_END)}


def _intervals(node):
    if isinstance(node, list):
        for item in node:
            yield from _intervals(item)
    elif isinstance(node, dict):
        if node.get('type') == 'INTERVAL':
            yield node
        for value in node.values():
            yield from _intervals(value)


def _without_dates(node):
    if isinstance(node, list):
        return [_without_dates(item) for item in node]
    if isinstance(node, dict):
        return {
            key: _without_dates(value)
            for key, value in node.items()
            if not (node.get('type') == 'INTERVAL' and key in ('start', 'end'))
        }
    return node


def test_widen_intervals_leaves_the_input_untouched():
    body = {
        'filter': {
            'type': 'AND',
            'fields': [{'type': 'INTERVAL', 'start': 'a', 'end': 'b'}],
        }
    }
    baseline.widen_intervals(body)
    assert body['filter']['fields'][0] == {'type': 'INTERVAL', 'start': 'a', 'end': 'b'}


def test_druid_times_reads_query_time_and_skips_other_lines():
    lines = [
        '2026-10-04T18:30:23.324Z\t172.24.0.10\t{"queryType":"groupBy"}\t{"query/time":172,"success":true}',
        '2026-10-04T18:30:24.000Z\t172.24.0.10\t{"queryType":"timeBoundary"}\t{"query/time":3}',
        'not a request line',
        '2026-10-04T18:30:25.000Z\t172.24.0.10\t{}\t{"success":false}',
    ]
    assert list(baseline.druid_times(lines)) == [172.0, 3.0]


def test_request_log_returns_only_new_complete_lines(tmp_path: Path):
    log = tmp_path / '2026-10-04.log'
    log.write_text('old\n')
    reader = baseline.RequestLog(tmp_path)
    with log.open('a') as handle:
        handle.write('first\nsecond\npartial')
    assert reader.drain() == ['first', 'second']
    with log.open('a') as handle:
        handle.write(' line\n')
    (tmp_path / '2026-10-05.log').write_text('next day\n')
    assert reader.drain() == ['partial line', 'next day']
    assert reader.drain() == []


def test_summarise_refuses_a_response_whose_size_changed():
    with pytest.raises(RuntimeError, match='size changed'):
        baseline.summarise('c', 'table', [1.0, 2.0], [10, 11], None)


def test_summarise_reports_druid_time_and_query_count():
    s = baseline.summarise(
        'c', 'line_graph', [10.0, 30.0, 20.0], [5, 5, 5], [(4, 2), (6, 2), (5, 2)]
    )
    assert (s.p50_ms, s.bytes, s.druid_ms, s.druid_queries, s.n) == (20.0, 5, 5.0, 2, 3)


@given(st.dictionaries(st.text(min_size=1), st.floats(1, 1e5), min_size=1))
def test_a_run_never_regresses_against_itself(p95s):
    run = [sample(case, p95) for case, p95 in p95s.items()]
    results = baseline.compare(run, run)
    assert not any(c.regressed or c.missing for c in results)


@given(st.floats(min_value=1, max_value=1e5), st.floats(min_value=0.5, max_value=2))
def test_regression_means_p95_more_than_ten_percent_higher(base_p95, factor):
    (result,) = baseline.compare(
        [sample('c', base_p95)], [sample('c', base_p95 * factor)]
    )
    assert result.regressed == (base_p95 * factor / base_p95 > 1.10)


def test_ten_percent_exactly_passes_and_just_over_fails():
    (at_limit,) = baseline.compare([sample('c', 100.0)], [sample('c', 110.0)])
    (over,) = baseline.compare([sample('c', 100.0)], [sample('c', 110.1)])
    assert not at_limit.regressed
    assert over.regressed


def test_a_lost_case_fails_and_a_new_case_does_not():
    results = baseline.compare(
        [sample('kept', 1), sample('lost', 1)], [sample('kept', 1), sample('added', 1)]
    )
    by_id = {c.case_id: c for c in results}
    assert by_id['lost'].missing
    assert not by_id['added'].missing and not by_id['added'].regressed


def test_compare_command_exit_codes(tmp_path: Path, capsys):
    base = tmp_path / 'base.jsonl'
    ok = tmp_path / 'ok.jsonl'
    slow = tmp_path / 'slow.jsonl'
    for path, p95 in ((base, 100.0), (ok, 105.0), (slow, 120.0)):
        path.write_text(json.dumps(sample('c', p95).__dict__) + '\n')
    assert baseline.main(['compare', str(base), str(ok)]) == 0
    assert baseline.main(['compare', str(base), str(slow)]) == 1
    assert 'REGRESSED' in capsys.readouterr().out


def test_samples_round_trip_through_jsonl(tmp_path: Path):
    samples = [sample('a', 12.5), PerfSample('b', 'map', 1, 2, 3, None, 30, 1, 2, None)]
    meta = {
        'git_sha': 'abc',
        'git_dirty': False,
        'started_utc': 'now',
        'host': {
            'cpu': 'x',
            'logical_cpus': 1,
            'memory_gib': 1,
            'kernel': 'k',
            'load_average_at_start': [0],
        },
        'method': {
            'rounds': 30,
            'warmup_rounds': 3,
            'concurrency': 1,
            'interval': 'i',
            'caches': 'warm',
        },
    }
    baseline.write_results(tmp_path / 'run', samples, meta)
    assert baseline.read_samples(tmp_path / 'run.jsonl') == samples
    assert '| b | map |' in (tmp_path / 'run.md').read_text()


def test_markdown_reports_the_host_load_at_start_and_end():
    meta = {
        'git_sha': 'abc',
        'git_dirty': False,
        'started_utc': 'now',
        'host': {
            'cpu': 'x',
            'logical_cpus': 16,
            'memory_gib': 1,
            'kernel': 'k',
            'load_average_at_start': [46.1, 53.53, 37.59],
            'load_average_at_end': [19.23, 34.08, 36.78],
        },
        'method': {
            'rounds': 100,
            'warmup_rounds': 3,
            'concurrency': 1,
            'interval': 'i',
            'caches': 'warm',
        },
    }
    text = baseline.markdown('run', [sample('a', 12.5)], meta)
    assert 'load [46.1, 53.53, 37.59] at start, [19.23, 34.08, 36.78] at end' in text


def test_summarise_dashboard_uses_the_query_percentiles_and_median_bytes():
    record = {
        'case_id': 'perf-mixed-6',
        'tiles': 6,
        'latencies_ms': [700.0, 900.0, 800.0],
        'bytes': [1859300, 1856230, 1859302],
        'query_requests': [6, 6, 6],
    }
    assert baseline.summarise_dashboard(record) == PerfSample(
        'perf-mixed-6', 'dashboard', 800.0, 890.0, 1859300, None, 3, 700.0, 900.0, None
    )


def test_summarise_dashboard_refuses_a_load_that_skipped_tile_queries():
    record = {
        'case_id': 'd',
        'tiles': 2,
        'latencies_ms': [1.0, 2.0],
        'bytes': [5, 5],
        'query_requests': [2, 1],
    }
    with pytest.raises(RuntimeError, match='query requests'):
        baseline.summarise_dashboard(record)


def test_split_cases_routes_dashboard_slugs_to_the_browser_run():
    slugs = baseline.dashboard_slugs()
    assert baseline.split_cases(None) == (list(baseline.CASES), slugs)
    assert baseline.split_cases(['calc_formula', slugs[0]]) == (
        ['calc_formula'],
        [slugs[0]],
    )


def test_every_reference_dashboard_tile_is_a_query_tile():
    specs = json.loads(baseline.DASHBOARD_SPECS.read_text())
    assert len(specs) == 3
    for slug, spec in specs.items():
        assert spec['items'], slug
        assert all(h['item']['type'] == 'QUERY_ITEM' for h in spec['items']), slug


# --- paired runs: reference and candidate interleaved on one host --------------

rounds = st.integers(min_value=1, max_value=60)


@given(rounds)
def test_each_round_runs_every_side_once_and_the_lead_alternates(n):
    order = [baseline.interleaved_order(i, baseline.SIDES) for i in range(n)]
    assert all(sorted(sides) == sorted(baseline.SIDES) for sides in order)
    leads = [sides[0] for sides in order]
    assert leads.count('reference') - leads.count('candidate') in (0, 1)
    assert all(a != b for a, b in zip(leads, leads[1:]))


def test_warm_up_rounds_run_on_both_sides_and_are_dropped():
    calls = []

    def measure(side):
        calls.append(side)
        return len(calls)

    results = baseline.run_interleaved(baseline.SIDES, 2, 1, measure)
    assert calls == [
        'reference',
        'candidate',
        'candidate',
        'reference',
        'reference',
        'candidate',
    ]
    assert results == {'reference': [4, 5], 'candidate': [3, 6]}


@given(
    st.floats(min_value=1, max_value=1e4),
    st.lists(st.floats(min_value=-0.09, max_value=0.09), min_size=2, max_size=400),
)
def test_an_a_a_run_passes_while_host_load_drifts_up_to_nine_percent_per_request(
    intrinsic_ms, steps
):
    # Host load as a multiplier per request slot, changing by at most 9% from
    # one request to the next (a 9% fall is a 1.099 ratio the other way): the two sides of a round see nearly the same
    # load, so identical code stays within the limit however far load wanders.
    load = [1.0]
    for step in steps:
        load.append(load[-1] * (1 + step))
    slot = iter(load)
    n = len(load) // 2

    def measure(side):
        return intrinsic_ms * next(slot)

    latencies = baseline.run_interleaved(baseline.SIDES, n, 0, measure)
    reference, candidate = (
        sample('c', baseline.percentile(latencies[side], 0.95))
        for side in baseline.SIDES
    )
    (result,) = baseline.compare([reference], [candidate])
    assert not result.regressed


def test_dashboard_lines_are_summarised_per_target():
    def line(target, ms):
        return json.dumps(
            {
                'case_id': 'd',
                'target': target,
                'tiles': 1,
                'latencies_ms': [ms, ms],
                'bytes': [5, 5],
                'query_requests': [1, 1],
            }
        )

    grouped = baseline.dashboard_samples_by_side(
        [line('reference', 100.0), line('candidate', 120.0), '']
    )
    assert {
        side: [s.p95_ms for s, _ in samples] for side, samples in grouped.items()
    } == {
        'reference': [100.0],
        'candidate': [120.0],
    }


def _paired_meta():
    return {
        'reference_sha': 'a' * 40,
        'candidate_sha': 'b' * 40,
        'git_dirty': False,
        'started_utc': 'now',
        'host': {
            'cpu': 'x',
            'logical_cpus': 16,
            'memory_gib': 1,
            'kernel': 'k',
            'load_average_at_start': [40.0, 1, 1],
            'load_average_at_end': [20.0, 1, 1],
        },
        'method': {
            'rounds': 100,
            'warmup_rounds': 3,
            'concurrency': 1,
            'interval': 'i',
            'caches': 'warm',
        },
    }


def test_a_paired_run_writes_both_sides_and_fails_on_a_clear_regression(
    tmp_path: Path, capsys
):
    stem = baseline.paired_stem(tmp_path, '2026-10-05', 'a' * 40, 'b' * 40, 'aa')
    assert stem == tmp_path / 'paired' / '2026-10-05-aaaaaaaaaa-vs-bbbbbbbbbb-aa'
    ms = [float(v) for v in range(100, 121)]
    reference = [sample('q', 119.0), sample('perf-mixed-6', 119.0)]
    rounds = {'q': (ms, ms), 'perf-mixed-6': (ms, ms)}
    assert (
        baseline.finish_paired(stem, reference, reference, rounds, _paired_meta()) == 0
    )
    assert baseline.read_samples(Path(f'{stem}.reference.jsonl')) == reference
    assert baseline.read_samples(Path(f'{stem}.candidate.jsonl')) == reference
    recorded = [
        json.loads(line)
        for line in Path(f'{stem}.rounds.jsonl').read_text().splitlines()
    ]
    assert recorded[0] == {'case_id': 'q', 'reference_ms': ms, 'candidate_ms': ms}
    text = Path(f'{stem}.md').read_text()
    assert '| q | 119.0 | 119.0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.100 | ok |' in text
    assert 'every case would have failed a slowdown of 1.100 or more' in text
    assert (
        'every case would have failed a slowdown of 1.100 or more'
        in capsys.readouterr().out
    )
    assert 'load [40.0, 1, 1] at start, [20.0, 1, 1] at end' in text
    slower = {'q': (ms, ms), 'perf-mixed-6': (ms, [v * 1.2 for v in ms])}
    assert (
        baseline.finish_paired(stem, reference, reference, slower, _paired_meta()) == 1
    )
    out = capsys.readouterr().out
    assert 'REGRESSED (p95, paired median)' in out
    assert 'FAIL: perf-mixed-6' in out


@given(
    st.lists(st.floats(min_value=1, max_value=1e4), min_size=20, max_size=120),
    st.floats(min_value=0.5, max_value=2),
)
def test_a_candidate_slower_by_a_constant_factor_fails_exactly_above_ten_percent(
    reference_ms, factor
):
    # Every resample of pairs scales by the same factor, so the bound equals it.
    result = baseline.paired_result(
        'c', reference_ms, [ms * factor for ms in reference_ms], 0.05, resamples=50
    )
    assert result.ratio == pytest.approx(factor)
    assert result.lower == pytest.approx(factor)
    assert result.regressed == (result.ratio > 1.10)


@given(st.lists(st.floats(min_value=1, max_value=1e4), min_size=20, max_size=120))
def test_identical_sides_never_regress(ms):
    result = baseline.paired_result('c', ms, list(ms), 0.05, resamples=50)
    assert result.ratio == 1 and not result.regressed


def test_paired_result_is_deterministic():
    reference = [float(v % 17 + 50) for v in range(100)]
    candidate = [float(v % 13 + 50) for v in range(100)]
    first = baseline.paired_result('c', reference, candidate, 0.002)
    assert baseline.paired_result('c', reference, candidate, 0.002) == first


def test_independent_stalls_trip_the_bare_p95_ratio_but_not_the_paired_verdict():
    # An A/A run on a loaded host, simulated: both sides share each round's
    # load, and one request in ten also stalls on its own for up to 3x. Taken
    # bare, some cases' p95 ratios land over 1.10; the confidence bound keeps
    # them from failing the run.
    rng = random.Random(20261005)

    def latency(load):
        stall = rng.uniform(1, 3) if rng.random() < 0.1 else 1
        return 50 * load * stall

    bare_over, regressed = 0, 0
    cases = 24
    for case in range(cases):
        reference, candidate = [], []
        for _ in range(100):
            load = rng.uniform(1, 3)
            reference.append(latency(load))
            candidate.append(latency(load))
        result = baseline.paired_result(f'c{case}', reference, candidate, 0.05 / cases)
        bare_over += result.ratio > 1.10
        regressed += result.regressed
    assert bare_over > 0
    assert regressed == 0


def _loaded_host_rounds(rng, factor, tail_every=0, rounds=100):
    """One case on the simulated loaded host above: a shared load per round,
    independent stalls per request, and the candidate `factor` times slower.
    With tail_every, every tail_every-th round the candidate alone takes 3x."""

    def latency(load):
        stall = rng.uniform(1, 3) if rng.random() < 0.1 else 1
        return 50 * load * stall

    reference, candidate = [], []
    for index in range(rounds):
        load = rng.uniform(1, 3)
        reference.append(latency(load))
        tail = 3 if tail_every and index % tail_every == 0 else 1
        candidate.append(latency(load) * factor * tail)
    return reference, candidate


def test_a_uniform_fifteen_percent_slowdown_fails_every_case_on_a_loaded_host():
    # The noise that keeps an A/A run from failing must not hide a real
    # regression: p95 alone cannot see 15% through these stalls, the paired
    # per-round ratio can.
    rng = random.Random(20261006)
    cases = 24
    for case in range(cases):
        reference, candidate = _loaded_host_rounds(rng, 1.15)
        result = baseline.paired_result(f'c{case}', reference, candidate, 0.05 / cases)
        assert result.regressed, result


def test_a_tail_regression_fails_on_p95_even_when_the_typical_request_is_unchanged():
    # A slow path one request in ten takes leaves the paired median at 1 and
    # triples p95; the p95 check still fires on its own.
    rng = random.Random(7)
    reference = [100 + rng.uniform(0, 5) for _ in range(100)]
    candidate = [
        ms * (3 if index % 10 == 0 else 1) for index, ms in enumerate(reference)
    ]
    result = baseline.paired_result('c', reference, candidate, 0.05 / 24)
    assert result.shift == pytest.approx(1)
    assert not result.shift_regressed
    assert result.p95_regressed and result.regressed


@given(
    st.lists(st.tuples(st.floats(1, 1e4), st.floats(1, 1e4)), min_size=20, max_size=60),
    st.floats(min_value=0.5, max_value=3),
)
def test_detects_is_the_smallest_uniform_slowdown_the_run_would_fail(pairs, factor):
    # p95, the median and the seeded bootstrap all scale with the candidate,
    # so scaling the candidate by `factor` fails exactly when factor > detects.
    reference = [r for r, _ in pairs]
    candidate = [c for _, c in pairs]
    detects = baseline.paired_result('c', reference, candidate, 0.05, 50).detects
    scaled = baseline.paired_result(
        'c', reference, [ms * factor for ms in candidate], 0.05, 50
    )
    if not math.isclose(factor, detects, rel_tol=1e-6):
        assert scaled.regressed == (factor > detects)


def test_paired_is_the_default_and_compare_selects_the_committed_baseline():
    assert baseline.parse_args([]).mode == 'paired'
    assert baseline.parse_args(['--committed']).mode == 'committed'
    committed = baseline.parse_args(['--compare'])
    assert (committed.mode, committed.compare) == ('committed', '')


def test_a_paired_verdict_needs_twenty_rounds():
    # Below about 20 pairs a bootstrap of p95 resamples little more than the
    # maximum, and an A/A case fails two to three times as often as its level.
    ms = [float(v) for v in range(1, 20)]
    with pytest.raises(ValueError, match='at least 20 rounds'):
        baseline.paired_result('c', ms, ms, 0.05)
    baseline.paired_result('c', ms + [20.0], ms + [20.0], 0.05)


@pytest.mark.parametrize('flag', ['--rounds', '--dashboard-rounds'])
def test_paired_mode_refuses_fewer_than_twenty_rounds(flag):
    with pytest.raises(SystemExit):
        baseline.parse_args([flag, '19'])
    assert baseline.parse_args([flag, '20']).mode == 'paired'
    assert baseline.parse_args(['--committed', flag, '5']).mode == 'committed'


def test_the_report_says_whether_the_reference_is_the_wps_base():
    # Decision 0011: the reference is `git merge-base HEAD mig/integration`;
    # only a phase-exit run uses another commit (the phase's start).
    meta = _paired_meta()
    meta['integration_merge_base'] = 'a' * 40
    text = '\n'.join(baseline.method_lines(meta))
    assert "the WP's base (merge base with mig/integration)" in text
    meta['integration_merge_base'] = 'c' * 40
    text = '\n'.join(baseline.method_lines(meta))
    assert f'not the merge base with mig/integration (`{"c" * 40}`)' in text



def test_the_reference_web_has_its_own_redis():
    # Decision 0011: from WP-1b the result cache lives in Redis, so a shared
    # Redis would let one side answer from bytes the other side cached.
    import yaml

    compose = yaml.safe_load((baseline.HERE / 'stack/web.yaml').read_text())
    services = compose['services']
    candidate_redis = services['web']['environment']['REDIS_HOST']
    reference_redis = services['web-reference']['environment']['REDIS_HOST']
    assert candidate_redis == 'redis'
    assert reference_redis != candidate_redis
    assert services[reference_redis]['profiles'] == ['reference']
    assert reference_redis in services['web-reference']['depends_on']
