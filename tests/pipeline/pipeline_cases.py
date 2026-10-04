"""The fixture cases. Each mirrors a real invocation or exercises one input format or flag.

Fixture data is synthetic: invented values and place names, never real health data.
Municipality codes in the ``yellow_fever`` fixture are public IBGE codes that exist in
``pipeline/harmony_demo/static_data/mapped_locations.csv``, so the demo join matches.
"""

from __future__ import annotations

from pipeline_fixtures import (
    FILL_DIMENSION_DATA,
    PROCESS_CSV,
    PROCESS_CSV_WRAPPER,
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

SYNTHETIC_MAPPING = '{work}/mapped_locations.csv'
SYNTHETIC_METADATA = '{work}/metadata_mapped.csv'
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
    mapping: str,
    metadata: str,
    *extra: str,
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


def _wide(name: str, *extra: str, fixture: str = 'process_csv/wide/input.csv') -> Case:
    return Case(
        name=name,
        inputs={'wide.csv': fixture},
        steps=(_process(*WIDE_ARGS, *extra, input_path='{work}/wide.csv'),),
    )


HANDMADE_INPUTS = {
    'processed_data.json.lz4': 'fill_dimension_data/base_rows.jsonl',
    **SYNTHETIC_LOCATION_INPUTS,
}
HANDMADE_INPUT_PATH = '{work}/processed_data.json.lz4'


def _cases() -> tuple[Case, ...]:
    yellow_fever_process = _process(*YELLOW_FEVER_ARGS, input_path='{work}/yellow_fever_cases.csv')
    yellow_fever_inputs = {'yellow_fever_cases.csv': 'process_csv/yellow_fever/input.csv'}
    tall_process_gz = _process(*TALL_ARGS, input_path='{work}/tall.csv.gz')
    return (
        # harmony_demo, exactly as Zeus runs it.
        Case(
            name='demo__yellow_fever_end_to_end',
            inputs=yellow_fever_inputs,
            steps=(
                yellow_fever_process,
                _fill(
                    '{static}/mapped_locations.csv',
                    '{static}/metadata_mapped.csv',
                    '--shard_size=3000000',
                ),
            ),
        ),
        # pipeline/harmony_demo/process/run/00_self_serve/10_process with no sources.
        Case(
            name='demo__self_serve_no_sources',
            steps=(
                Step(
                    PROCESS_CSV,
                    ('--sourcename', '', '--prefix', '', '--input', '/dev/null', *PROCESS_OUTPUTS),
                ),
            ),
        ),
        # The same step with one source, through the self-serve wrapper.
        Case(
            name='demo__self_serve_wrapper',
            inputs={
                'clinic_survey/config.json': 'self_serve/clinic_survey/config.json',
                'clinic_survey/clinic_survey.csv.gz': 'self_serve/clinic_survey/clinic_survey.csv',
                **SYNTHETIC_LOCATION_INPUTS,
            },
            steps=(
                Step(
                    PROCESS_CSV_WRAPPER,
                    ('--input_dir={work}/clinic_survey', *PROCESS_OUTPUTS),
                ),
                _fill(SYNTHETIC_MAPPING, SYNTHETIC_METADATA, '--shard_size=3000000'),
            ),
        ),
        # Input formats: tall (field, val), gzip, lz4, tab-delimited, plain wide.
        Case(
            name='process_csv__tall_gzip',
            inputs={'tall.csv.gz': 'process_csv/tall/input.csv'},
            steps=(tall_process_gz,),
        ),
        Case(
            name='process_csv__tall_lz4',
            inputs={'tall.csv.lz4': 'process_csv/tall/input.csv'},
            steps=(_process(*TALL_ARGS, input_path='{work}/tall.csv.lz4'),),
        ),
        Case(
            name='process_csv__wide_tab_delimited',
            inputs={'wide.tsv': 'process_csv/wide_tab/input.tsv'},
            steps=(_process(*WIDE_ARGS, '--delimiter=\\t', input_path='{work}/wide.tsv'),),
        ),
        _wide('process_csv__wide', '--output_indicators={out}/indicators.json'),
        # Flags.
        _wide('process_csv__wide_disable_rollup', '--disable_rollup'),
        _wide('process_csv__wide_exclude_zeros', '--exclude_zeros'),
        _wide('process_csv__wide_tracer_field', '--tracer_field', 'demo_facility_count'),
        _wide('process_csv__wide_disaggregate', '--disaggregate', 'Malaria Positive:Sex,Death'),
        _wide(
            'process_csv__wide_flatten_string_categories',
            '--flatten_string_categories',
            '--fields',
            'Malaria Positive',
            'Status',
        ),
        _wide(
            'process_csv__wide_join_cols', '--join_cols', 'Outcome+Gender:Death', '--join_str', '/'
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
        Case(
            name='process_csv__val_clean_regex',
            inputs={'dirty.csv': 'process_csv/dirty_values/input.csv'},
            steps=(
                _process(
                    '--date',
                    'Date',
                    '--prefix',
                    'demo',
                    '--sourcename',
                    'demo_dirty',
                    '--fields',
                    'Doses Given',
                    '--val_clean_regex',
                    '[,~]|n/a',
                    input_path='{work}/dirty.csv',
                ),
            ),
        ),
        Case(
            name='process_csv__bad_value_aborts',
            inputs={'dirty.csv': 'process_csv/dirty_values/input.csv'},
            steps=(
                _process(
                    '--date',
                    'Date',
                    '--prefix',
                    'demo',
                    '--sourcename',
                    'demo_dirty',
                    '--fields',
                    'Doses Given',
                    input_path='{work}/dirty.csv',
                    expect_returncode=1,
                ),
            ),
        ),
        Case(
            name='process_csv__field_wildcards',
            inputs={'wildcard.csv': 'process_csv/wildcard_numeric/input.csv'},
            steps=(
                _process(
                    '--date',
                    'Date',
                    '--prefix',
                    'demo',
                    '--sourcename',
                    'demo_wildcard',
                    '--enable_field_wildcards',
                    input_path='{work}/wildcard.csv',
                ),
            ),
        ),
        Case(
            name='process_csv__field_wildcards_flatten_categories',
            inputs={'wildcard.csv': 'process_csv/wildcard_categories/input.csv'},
            steps=(
                _process(
                    '--date',
                    'Date',
                    '--prefix',
                    'demo',
                    '--sourcename',
                    'demo_wildcard',
                    '--enable_field_wildcards',
                    '--flatten_string_categories',
                    input_path='{work}/wildcard.csv',
                ),
            ),
        ),
        # fill_dimension_data: the location join on synthetic mappings.
        Case(
            name='fill_dimension_data__tall_synthetic_join',
            inputs={'tall.csv.gz': 'process_csv/tall/input.csv', **SYNTHETIC_LOCATION_INPUTS},
            steps=(
                tall_process_gz,
                _fill(
                    SYNTHETIC_MAPPING,
                    SYNTHETIC_METADATA,
                    '--shard_size=4',
                    '--ignore_missing_canonical_match',
                ),
            ),
        ),
        Case(
            name='fill_dimension_data__unmatched_location_aborts',
            inputs={'tall.csv.gz': 'process_csv/tall/input.csv', **SYNTHETIC_LOCATION_INPUTS},
            steps=(
                tall_process_gz,
                _fill(
                    SYNTHETIC_MAPPING,
                    SYNTHETIC_METADATA,
                    '--shard_size=3000000',
                    expect_returncode=1,
                ),
            ),
        ),
        Case(
            name='fill_dimension_data__default_shard_size',
            inputs=yellow_fever_inputs,
            steps=(
                yellow_fever_process,
                _fill('{static}/mapped_locations.csv', '{static}/metadata_mapped.csv'),
            ),
        ),
        Case(
            name='fill_dimension_data__handmade_rows_ignore_flags',
            inputs=HANDMADE_INPUTS,
            steps=(
                _fill(
                    SYNTHETIC_MAPPING,
                    SYNTHETIC_METADATA,
                    '--shard_size=3000000',
                    '--ignore_missing_date',
                    '--ignore_empty_data',
                    '--ignore_missing_canonical_match',
                    input_path=HANDMADE_INPUT_PATH,
                ),
            ),
        ),
        Case(
            name='fill_dimension_data__handmade_rows_experimental_parser',
            inputs=HANDMADE_INPUTS,
            steps=(
                _fill(
                    SYNTHETIC_MAPPING,
                    SYNTHETIC_METADATA,
                    '--shard_size=3000000',
                    '--ignore_missing_date',
                    '--ignore_empty_data',
                    '--ignore_missing_canonical_match',
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
                    SYNTHETIC_MAPPING,
                    SYNTHETIC_METADATA,
                    '--shard_size=3000000',
                    input_path=HANDMADE_INPUT_PATH,
                    expect_returncode=1,
                ),
            ),
        ),
    )


CASES: dict[str, Case] = {case.name: case for case in _cases()}
assert len(CASES) == len(_cases()), 'duplicate case names'
