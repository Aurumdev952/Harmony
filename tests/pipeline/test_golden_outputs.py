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
    NESTED_DATA_COLUMN,
    PROCESS_CSV,
    Case,
    Step,
    canonical_rows,
    capture_raw,
    contract_columns,
    contract_rollup,
    golden_files,
    layers,
    run_case,
)

CASE_NAMES = sorted(CASES)
LAYERS = ('contract', 'canonical', 'raw')

CaseLayers = dict[str, dict[str, bytes]]


@pytest.fixture(name='case_layers', scope='session')
def fixture_case_layers(tmp_path_factory) -> Callable[[str], CaseLayers]:
    """Run each case once per session; tests share its outputs."""
    cache: dict[str, CaseLayers] = {}

    def outputs(name: str) -> CaseLayers:
        if name not in cache:
            cache[name] = layers(
                capture_raw(run_case(CASES[name], tmp_path_factory.mktemp(name)))
            )
        return cache[name]

    return outputs


def test_every_case_has_a_golden_and_every_golden_a_case():
    golden_cases = {path.name for path in GOLDEN_DIR.iterdir() if path.is_dir()}
    assert golden_cases == set(CASES)


def test_every_case_that_completes_pins_druid_rows():
    for name, case in CASES.items():
        if not case.aborts:
            assert golden_files(name, 'contract'), f'{name} has no contract layer'


@pytest.mark.parametrize('layer', LAYERS)
@pytest.mark.parametrize('case', CASE_NAMES)
def test_outputs_match_golden(case, layer, case_layers):
    actual = case_layers(case)[layer]
    expected = golden_files(case, layer)
    file_set_changed = f'{case}/{layer}: output file set changed'
    assert sorted(actual) == sorted(expected), file_set_changed
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


@pytest.mark.parametrize(
    'case',
    ['demo__yellow_fever_end_to_end', 'fill_dimension_data__tall_synthetic_join'],
)
def test_outputs_do_not_depend_on_hash_seed(case, tmp_path):
    first = capture_raw(run_case(CASES[case], tmp_path / 'seed1', hash_seed='1'))
    second = capture_raw(run_case(CASES[case], tmp_path / 'seed2', hash_seed='2'))
    assert first == second


def test_gzip_and_lz4_inputs_read_the_same_rows(case_layers):
    assert case_layers('process_csv__tall_gzip') == case_layers('process_csv__tall_lz4')


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


def _typed_table_round_trip(rows: list[dict]) -> list[dict]:
    """What a typed columnar writer (Polars to Parquet, then to_dicts) returns.

    Every row gets every column, missing ones as null. A column holding any list
    becomes a list column, so its scalars become one-element lists. ``val`` becomes a
    float column, and the nestedJson ``data`` object a struct with every field.
    """
    columns = sorted({column for row in rows for column in row})
    list_columns = {
        column
        for column in columns
        if any(isinstance(row.get(column), list) for row in rows)
    }
    struct_fields = sorted(
        {field for row in rows for field in (row.get(NESTED_DATA_COLUMN) or {})}
    )
    typed = []
    for row in rows:
        out = {}
        for column in columns:
            value = row.get(column)
            if column == NESTED_DATA_COLUMN and value is not None:
                value = {field: value.get(field) for field in struct_fields}
            elif column == 'val' and value is not None:
                value = float(value)
            elif (
                column in list_columns
                and value is not None
                and not isinstance(value, list)
            ):
                value = [value]
            out[column] = value
        typed.append(out)
    return typed


@pytest.mark.parametrize(
    'case', [name for name in CASE_NAMES if golden_files(name, 'contract')]
)
def test_contract_survives_a_typed_table_round_trip(case):
    """A Parquet rewrite that stores the same Druid rows reproduces contract/."""
    rows = [
        json.loads(line)
        for line in golden_files(case, 'canonical')
        .get('druid_rows.jsonl', b'')
        .decode('utf-8')
        .splitlines()
    ]
    typed = _typed_table_round_trip(rows)
    assert contract_rollup(typed) == contract_rollup(rows)
    assert contract_columns(typed) == contract_columns(rows)


def test_contract_compares_dimensions_as_druid_stores_them():
    base = {'StateName': 'Northvale', 'field': 'demo_a', 'val': 1}
    same = [
        ({'Sex': None}, {}),
        ({'Sex': []}, {}),
        ({'Sex': ['F']}, {'Sex': 'F'}),
        ({'Sex': ['X', 'F']}, {'Sex': ['F', 'X']}),
    ]
    for left, right in same:
        assert contract_rollup([{**base, **left}]) == contract_rollup(
            [{**base, **right}]
        )
    assert contract_rollup([{**base, 'Sex': ''}]) != contract_rollup([base])


def test_canonical_rows_keep_integer_and_float_apart():
    assert canonical_rows([{'val': 1}]) != canonical_rows([{'val': 1.0}])


def test_contract_rollup_explodes_collapsed_zero_fields():
    rows = [
        {'StateName': 'Northvale', 'field': ['demo_a', 'demo_b'], 'val': 0},
        {'StateName': 'Northvale', 'field': 'demo_a', 'val': 2},
        {'StateName': 'Northvale', 'data': {'demo_c': 0.5}},
    ]
    facts = {}
    for line in contract_rollup(rows).splitlines():
        fact = json.loads(line)
        assert fact['dimensions']['StateName'] == 'Northvale'
        facts[fact['dimensions']['field']] = (
            fact['count'],
            fact['sum'],
            fact['min'],
            fact['max'],
        )
    assert facts == {
        'demo_a': (2, 2.0, 0.0, 2.0),
        'demo_b': (1, 0.0, 0.0, 0.0),
        'demo_c': (1, 0.5, 0.5, 0.5),
    }
