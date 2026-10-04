"""The pipeline steps produce the golden outputs for every fixture case."""

from __future__ import annotations

import datetime
import difflib
import json
from typing import Callable

import pytest
from pipeline_cases import CASES, PROCESS_OUTPUTS, TALL_ARGS
from pipeline_fixtures import (
    GOLDEN_DIR,
    PROCESS_CSV,
    Case,
    Step,
    canonical_rollup,
    canonical_rows,
    canonicalise,
    capture_raw,
    golden_files,
    run_case,
)

CASE_NAMES = sorted(CASES)


@pytest.fixture(scope='session')
def case_outputs(tmp_path_factory) -> Callable[[str], tuple[dict[str, bytes], dict[str, str]]]:
    """Run each case once per session; tests share its outputs."""
    cache: dict[str, tuple[dict[str, bytes], dict[str, str]]] = {}

    def outputs(name: str) -> tuple[dict[str, bytes], dict[str, str]]:
        if name not in cache:
            raw = capture_raw(run_case(CASES[name], tmp_path_factory.mktemp(name)))
            cache[name] = (raw, canonicalise(raw))
        return cache[name]

    return outputs


def _assert_same_files(case: str, layer: str, actual: dict[str, bytes]) -> None:
    expected = golden_files(case, layer)
    assert expected, f'no golden for {case}/{layer}; run tests/pipeline/run.sh regenerate'
    assert sorted(actual) == sorted(expected), f'{case}/{layer}: output file set changed'
    for name in sorted(expected):
        if actual[name] == expected[name]:
            continue
        diff = difflib.unified_diff(
            expected[name].decode('utf-8', 'replace').splitlines(keepends=True),
            actual[name].decode('utf-8', 'replace').splitlines(keepends=True),
            fromfile=f'golden/{case}/{layer}/{name}',
            tofile='actual',
        )
        pytest.fail(f'{case}/{layer}/{name} differs:\n{"".join(diff)}'[:20000])


def test_every_case_has_a_golden_and_every_golden_a_case():
    golden_cases = {path.name for path in GOLDEN_DIR.iterdir() if path.is_dir()}
    assert golden_cases == set(CASES)


@pytest.mark.parametrize('case', CASE_NAMES)
def test_raw_outputs_match_golden(case, case_outputs):
    raw, _ = case_outputs(case)
    _assert_same_files(case, 'raw', raw)


@pytest.mark.parametrize('case', CASE_NAMES)
def test_canonical_outputs_match_golden(case, case_outputs):
    _, canonical = case_outputs(case)
    if CASES[case].aborts:
        assert canonical == {}
        return
    _assert_same_files(
        case, 'canonical', {name: text.encode('utf-8') for name, text in canonical.items()}
    )


@pytest.mark.parametrize(
    'case', ['demo__yellow_fever_end_to_end', 'fill_dimension_data__tall_synthetic_join']
)
def test_outputs_do_not_depend_on_hash_seed(case, tmp_path):
    first = capture_raw(run_case(CASES[case], tmp_path / 'seed1', hash_seed='1'))
    second = capture_raw(run_case(CASES[case], tmp_path / 'seed2', hash_seed='2'))
    assert first == second


def test_gzip_and_lz4_inputs_read_the_same_rows(case_outputs):
    gz_raw, _ = case_outputs('process_csv__tall_gzip')
    lz4_raw, _ = case_outputs('process_csv__tall_lz4')
    assert gz_raw == lz4_raw


def test_without_date_column_rows_are_dated_today(tmp_path):
    """No --date stamps every row with the run date, so it cannot be a golden file."""
    case = Case(
        name='process_csv__no_date',
        inputs={'tall.csv': 'process_csv/tall/input.csv'},
        steps=(
            Step(
                PROCESS_CSV,
                (
                    *[arg for arg in TALL_ARGS if arg not in ('--date', 'Date')],
                    '--input={work}/tall.csv',
                    *PROCESS_OUTPUTS,
                ),
            ),
        ),
    )
    before = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    raw = capture_raw(run_case(case, tmp_path))
    after = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    rows = [json.loads(line) for line in raw['processed_data.json'].splitlines()]
    assert rows
    assert {row['Real_Date'] for row in rows} <= {before, after}


def test_canonical_rows_keep_integer_and_float_apart():
    assert canonical_rows([{'val': 1}]) != canonical_rows([{'val': 1.0}])


def test_canonical_rollup_explodes_collapsed_zero_fields():
    rows = [
        {'StateName': 'Northvale', 'field': ['demo_a', 'demo_b'], 'val': 0},
        {'StateName': 'Northvale', 'field': 'demo_a', 'val': 2},
        {'StateName': 'Northvale', 'data': {'demo_c': 0.5}},
    ]
    facts = {}
    for line in canonical_rollup(rows).splitlines():
        fact = json.loads(line)
        assert fact['dimensions']['StateName'] == 'Northvale'
        facts[fact['dimensions']['field']] = (fact['count'], fact['sum'], fact['min'], fact['max'])
    assert facts == {
        'demo_a': (2, 2.0, 0.0, 2.0),
        'demo_b': (1, 0.0, 0.0, 0.0),
        'demo_c': (1, 0.5, 0.5, 0.5),
    }
