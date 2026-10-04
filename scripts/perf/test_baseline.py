"""Tests for the offline parts of baseline.py: statistics, case loading, the
request-log reader and the PERF-7 comparison.

    uv run --no-project --with pytest --with hypothesis python -m pytest scripts/perf
"""

from __future__ import annotations

import json
import math
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
