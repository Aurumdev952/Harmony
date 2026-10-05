"""The fixture cases. Each mirrors a real invocation, or exercises an input format.

Every case that does not abort runs through ``fill_dimension_data``, so each one pins
Druid rows (the ``contract/`` layer), not only the intermediate base rows.

Fixture data is synthetic: invented values and place names, never real health data.
Municipality codes in the ``yellow_fever`` fixture are public IBGE codes that exist in
``pipeline/harmony_demo/static_data/mapped_locations.csv``, so the demo join matches.
"""

from __future__ import annotations

from pipeline_fixtures import (
    FILL_DIMENSION_DATA,
    PROCESS_CSV,
    PROCESS_CSV_WRAPPER,
    SUITE_DIR,
    Case,
    Step,
)

PROCESS_OUTPUTS = (
    '--output_locations={out}/locations.csv',
    '--output_fields={out}/fields.csv',
    '--output_rows={out}/processed_data.json.lz4',
)

# pipeline/harmony_demo/process/run/00_yellow_fever/10_process
YELLOW_FEVER_ARGS = (
    '--delimiter',
    ';',
    '--rename_cols',
    'COD_MUN_LPI:MunicipalityName',
    'SEXO:Sex',
    'IDADE:Age',
    'OBITO:Death',
    '--date',
    'DT_IS',
    '--prefix',
    'yellow_fever',
    '--sourcename',
    'yellow_fever',
    '--set_cols',
    'cases:1',
    'test_indicator:5',
    '--fields',
    'cases',
    'test_indicator',
)

TALL_ARGS = ('--date', 'Date', '--prefix', 'demo', '--sourcename', 'demo_tall')

WIDE_ARGS = (
    '--rename_cols',
    'Region:StateName',
    'District:MunicipalityName',
    'Gender:Sex',
    'AgeGroup:Age',
    'Outcome:Death',
    '--date',
    'ReportDate',
    '--prefix',
    'demo',
    '--sourcename',
    'demo_wide',
    '--fields',
    'Malaria Positive',
    'Malaria Tested',
)

SYNTHETIC_LOCATION_INPUTS = {
    'mapped_locations.csv': 'locations/mapped_locations.csv',
    'metadata_mapped.csv': 'locations/metadata_mapped.csv',
}


def _process(*args: str, input_path: str, expect_returncode: int = 0) -> Step:
    return Step(
        PROCESS_CSV,
        (*args, f'--input={input_path}', *PROCESS_OUTPUTS),
        expect_returncode,
    )


def _fill(
    *extra: str,
    mapping: str = '{work}/mapped_locations.csv',
    metadata: str = '{work}/metadata_mapped.csv',
    input_path: str = '{out}/processed_data.json.lz4',
    expect_returncode: int = 0,
) -> Step:
    """pipeline/harmony_demo/process/run/90_shared/10_fill_dimension_data.abort_fail"""
    return Step(
        FILL_DIMENSION_DATA,
        (
            f'--location_mapping_file={mapping}',
            f'--metadata_file={metadata}',
            f'--input_file={input_path}',
            '--output_file_pattern={out}/processed_rows.#.json.gz',
            '--metadata_digest_file={out}/metadata_digest_file.csv',
            *extra,
        ),
        expect_returncode,
    )


DEMO_FILL = _fill(
    '--shard_size=3000000',
    mapping='{static}/mapped_locations.csv',
    metadata='{static}/metadata_mapped.csv',
)
SYNTHETIC_FILL = _fill('--shard_size=3000000')
# The tall fixture holds one location (Westfold) that no mapping knows.
SYNTHETIC_FILL_SKIP_UNMATCHED = _fill(
    '--shard_size=3000000', '--ignore_missing_canonical_match'
)


def _joined(
    name: str,
    fixture: str,
    input_name: str,
    *args: str,
    fill: Step = SYNTHETIC_FILL,
) -> Case:
    """process_csv on one fixture, then the shared join on the synthetic mapping."""
    return Case(
        name=name,
        inputs={input_name: fixture, **SYNTHETIC_LOCATION_INPUTS},
        steps=(_process(*args, input_path=f'{{work}}/{input_name}'), fill),
    )


def _wide(name: str, *extra: str) -> Case:
    return _joined(name, 'process_csv/wide/input.csv', 'wide.csv', *WIDE_ARGS, *extra)


def _tall(name: str, input_name: str, *extra: str) -> Case:
    return _joined(
        name,
        'process_csv/tall/input.csv',
        input_name,
        *TALL_ARGS,
        *extra,
        fill=SYNTHETIC_FILL_SKIP_UNMATCHED,
    )


def _self_serve_wrapper(source: str) -> Step:
    return Step(
        PROCESS_CSV_WRAPPER,
        (
            f'--input_dir={{work}}/{source}',
            f'--output_locations={{out}}/locations_{source}.csv',
            f'--output_fields={{out}}/fields_{source}.csv',
            f'--output_rows={{out}}/processed_data_{source}.json.lz4',
        ),
    )


def _self_serve_inputs(source: str) -> dict[str, str]:
    """The fetch step's layout: config.json and the gzipped data file per source."""
    return {
        f'{source}/config.json': f'self_serve/{source}/config.json',
        f'{source}/{source}.csv.gz': f'self_serve/{source}/{source}.csv',
    }


HANDMADE_INPUTS = {
    'processed_data.json.lz4': 'fill_dimension_data/base_rows.jsonl',
    **SYNTHETIC_LOCATION_INPUTS,
}
HANDMADE_INPUT_PATH = '{work}/processed_data.json.lz4'
HANDMADE_IGNORE_FLAGS = (
    '--shard_size=3000000',
    '--ignore_missing_date',
    '--ignore_empty_data',
    '--ignore_missing_canonical_match',
)


def _cases() -> tuple[Case, ...]:
    yellow_fever_process = _process(
        *YELLOW_FEVER_ARGS, input_path='{work}/yellow_fever_cases.csv'
    )
    yellow_fever_inputs = {
        'yellow_fever_cases.csv': 'process_csv/yellow_fever/input.csv'
    }
    dirty_args = (
        '--date',
        'Date',
        '--prefix',
        'demo',
        '--sourcename',
        'demo_dirty',
        '--fields',
        'Doses Given',
    )
    return (
        # harmony_demo, exactly as Zeus runs it.
        Case(
            name='demo__yellow_fever_end_to_end',
            inputs=yellow_fever_inputs,
            steps=(yellow_fever_process, DEMO_FILL),
        ),
        # pipeline/harmony_demo/process/run/00_self_serve/10_process with no sources.
        Case(
            name='demo__self_serve_no_sources',
            inputs=SYNTHETIC_LOCATION_INPUTS,
            steps=(
                Step(
                    PROCESS_CSV,
                    (
                        '--sourcename',
                        '',
                        '--prefix',
                        '',
                        '--input',
                        '/dev/null',
                        *PROCESS_OUTPUTS,
                    ),
                ),
                SYNTHETIC_FILL,
            ),
        ),
        # The same step with two sources: one wrapper run per source, then the merge.
        Case(
            name='demo__self_serve_two_sources',
            inputs={
                **_self_serve_inputs('clinic_survey'),
                **_self_serve_inputs('outreach_log'),
                **SYNTHETIC_LOCATION_INPUTS,
            },
            steps=(
                _self_serve_wrapper('clinic_survey'),
                _self_serve_wrapper('outreach_log'),
                Step(SUITE_DIR / 'self_serve_merge.sh', ('{out}',), bash=True),
                SYNTHETIC_FILL,
            ),
        ),
        # Input formats: tall (field, val) as gzip and lz4, tab-delimited, plain wide.
        _tall('process_csv__tall_gzip', 'tall.csv.gz'),
        _tall('process_csv__tall_lz4', 'tall.csv.lz4'),
        _tall(
            'process_csv__tall_disaggregate',
            'tall.csv',
            '--disaggregate',
            'Malaria Positive:Sex,Age',
            '*:Death',
        ),
        _joined(
            'process_csv__tall_value_column',
            'process_csv/tall_value_column/input.csv',
            'tall_value_column.csv',
            *TALL_ARGS,
            '--value',
            'Count',
        ),
        _joined(
            'process_csv__wide_tab_delimited',
            'process_csv/wide_tab/input.tsv',
            'wide.tsv',
            *WIDE_ARGS,
            '--delimiter=\\t',
        ),
        _wide('process_csv__wide', '--output_indicators={out}/indicators.json'),
        # Flags.
        _wide('process_csv__wide_disable_rollup', '--disable_rollup'),
        _wide('process_csv__wide_exclude_zeros', '--exclude_zeros'),
        _wide(
            'process_csv__wide_tracer_field', '--tracer_field', 'demo_facility_count'
        ),
        _wide(
            'process_csv__wide_disaggregate',
            '--disaggregate',
            'Malaria Positive:Sex,Death',
        ),
        _wide(
            'process_csv__wide_disaggregate_exclude_zeros',
            '--disaggregate',
            'Malaria Positive:Sex,Death',
            '--exclude_zeros',
        ),
        _wide(
            'process_csv__wide_flatten_string_categories',
            '--flatten_string_categories',
            '--fields',
            'Malaria Positive',
            'Status',
        ),
        _wide(
            'process_csv__wide_join_cols',
            '--join_cols',
            'Outcome+Gender:Death',
            '--join_str',
            '/',
        ),
        _wide(
            'process_csv__wide_multi_value_dimensions',
            '--multi_value_dimensions',
            'Sex:Gender,AltGender',
        ),
        _wide(
            'process_csv__wide_dimensions_subset',
            '--dimensions',
            'StateName',
            'MunicipalityName',
        ),
        _joined(
            'process_csv__val_clean_regex',
            'process_csv/dirty_values/input.csv',
            'dirty.csv',
            *dirty_args,
            '--val_clean_regex',
            '[,~]|n/a',
        ),
        Case(
            name='process_csv__bad_value_aborts',
            inputs={'dirty.csv': 'process_csv/dirty_values/input.csv'},
            steps=(
                _process(
                    *dirty_args, input_path='{work}/dirty.csv', expect_returncode=1
                ),
            ),
        ),
        _joined(
            'process_csv__field_wildcards',
            'process_csv/wildcard_numeric/input.csv',
            'wildcard.csv',
            '--date',
            'Date',
            '--prefix',
            'demo',
            '--sourcename',
            'demo_wildcard',
            '--enable_field_wildcards',
        ),
        _joined(
            'process_csv__field_wildcards_flatten_categories',
            'process_csv/wildcard_categories/input.csv',
            'wildcard.csv',
            '--date',
            'Date',
            '--prefix',
            'demo',
            '--sourcename',
            'demo_wildcard',
            '--enable_field_wildcards',
            '--flatten_string_categories',
        ),
        # fill_dimension_data: the location join on synthetic mappings.
        Case(
            name='fill_dimension_data__tall_synthetic_join',
            inputs={
                'tall.csv.gz': 'process_csv/tall/input.csv',
                **SYNTHETIC_LOCATION_INPUTS,
            },
            steps=(
                _process(*TALL_ARGS, input_path='{work}/tall.csv.gz'),
                _fill('--shard_size=4', '--ignore_missing_canonical_match'),
            ),
        ),
        Case(
            name='fill_dimension_data__unmatched_location_aborts',
            inputs={
                'tall.csv.gz': 'process_csv/tall/input.csv',
                **SYNTHETIC_LOCATION_INPUTS,
            },
            steps=(
                _process(*TALL_ARGS, input_path='{work}/tall.csv.gz'),
                _fill('--shard_size=3000000', expect_returncode=1),
            ),
        ),
        Case(
            name='fill_dimension_data__default_shard_size',
            inputs=yellow_fever_inputs,
            steps=(
                yellow_fever_process,
                _fill(
                    mapping='{static}/mapped_locations.csv',
                    metadata='{static}/metadata_mapped.csv',
                ),
            ),
        ),
        Case(
            name='fill_dimension_data__handmade_rows_ignore_flags',
            inputs=HANDMADE_INPUTS,
            steps=(_fill(*HANDMADE_IGNORE_FLAGS, input_path=HANDMADE_INPUT_PATH),),
        ),
        Case(
            name='fill_dimension_data__handmade_rows_experimental_parser',
            inputs=HANDMADE_INPUTS,
            steps=(
                _fill(
                    *HANDMADE_IGNORE_FLAGS,
                    '--use_experimental_parser',
                    input_path=HANDMADE_INPUT_PATH,
                ),
            ),
        ),
        Case(
            name='fill_dimension_data__missing_date_aborts',
            inputs=HANDMADE_INPUTS,
            steps=(
                _fill(
                    '--shard_size=3000000',
                    input_path=HANDMADE_INPUT_PATH,
                    expect_returncode=1,
                ),
            ),
        ),
    )


CASES: dict[str, Case] = {case.name: case for case in _cases()}
assert len(CASES) == len(_cases()), 'duplicate case names'
