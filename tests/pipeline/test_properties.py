"""Properties of the per-row pipeline code that a reimplementation must keep.

These run the pipeline modules in process, so they import ``config`` for harmony_demo.
"""

from __future__ import annotations

import csv
import datetime
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from pipeline_fixtures import REPO_ROOT

if os.environ.setdefault('ZEN_ENV', 'harmony_demo') != 'harmony_demo':
    raise RuntimeError('tests/pipeline imports config for ZEN_ENV=harmony_demo only')
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.datatypes import BaseRowType, DimensionFactoryType  # noqa: E402, I001
from data.pipeline.scripts.process_csv import Aggregator, _get_date  # noqa: E402

PIPELINE_SETTINGS = settings(database=None, deadline=None)

DATES = st.dates(
    min_value=datetime.date(1900, 1, 1), max_value=datetime.date(2099, 12, 31)
)


@PIPELINE_SETTINGS
@given(DATES)
def test_iso_dates_parse_to_themselves(date):
    assert _get_date(date.isoformat()) == date.isoformat()


@PIPELINE_SETTINGS
@given(DATES, st.times())
def test_iso_datetimes_keep_their_date(date, time):
    assert (
        _get_date(f'{date.isoformat()}T{time.strftime("%H:%M:%S")}') == date.isoformat()
    )


@PIPELINE_SETTINGS
@given(DATES)
def test_slash_dates_are_month_first_unless_the_first_number_exceeds_twelve(date):
    """dateutil reads DD/MM/YYYY as MM/DD/YYYY whenever the day could be a month."""
    text = f'{date.day:02d}/{date.month:02d}/{date.year}'
    expected = date if date.day > 12 else datetime.date(date.year, date.day, date.month)
    assert _get_date(text) == expected.isoformat()


# Location names never contain the "__" key delimiter here; see the collision test.
LOCATION_NAMES = st.text(
    alphabet=st.characters(blacklist_categories=('Cs', 'Cc'), blacklist_characters='_'),
    min_size=1,
    max_size=8,
)
CLEAN_KEYS = st.tuples(LOCATION_NAMES, st.one_of(st.just(''), LOCATION_NAMES))
CANONICAL_KEYS = st.tuples(LOCATION_NAMES, LOCATION_NAMES)
METADATA_COLUMNS = ('StateID', 'MunicipalityID', 'MunicipalityLat', 'MunicipalityLon')


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with open(path, 'w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _metadata_collector(
    mapping: dict[tuple[str, str], tuple[str, str]],
    metadata: dict[tuple[str, str], dict[str, str]],
    directory: Path,
):
    mapping_path = directory / 'mapped_locations.csv'
    metadata_path = directory / 'metadata_mapped.csv'
    _write_csv(
        mapping_path,
        [
            'CleanStateName',
            'CleanMunicipalityName',
            'CanonicalStateName',
            'CanonicalMunicipalityName',
        ],
        [[*clean, *canonical] for clean, canonical in mapping.items()],
    )
    _write_csv(
        metadata_path,
        ['StateName', 'MunicipalityName', *METADATA_COLUMNS],
        [
            [*key, *(values[column] for column in METADATA_COLUMNS)]
            for key, values in metadata.items()
        ],
    )
    return DimensionFactoryType.create_metadata_collector(
        str(metadata_path), str(mapping_path)
    )


@st.composite
def location_tables(draw):
    canonical_keys = draw(st.lists(CANONICAL_KEYS, min_size=1, max_size=6, unique=True))
    mapping = draw(
        st.dictionaries(
            CLEAN_KEYS, st.sampled_from(canonical_keys), min_size=1, max_size=10
        )
    )
    with_metadata = draw(st.lists(st.sampled_from(canonical_keys), unique=True))
    metadata = {
        key: {column: draw(LOCATION_NAMES) for column in METADATA_COLUMNS}
        for key in with_metadata
    }
    unmapped = draw(CLEAN_KEYS.filter(lambda key: key not in mapping))
    return mapping, metadata, unmapped


@PIPELINE_SETTINGS
@given(location_tables())
def test_location_join_returns_canonical_names_and_their_metadata(tables):
    """Oracle: the join is a lookup of the clean key, then of the canonical key."""
    mapping, metadata, unmapped = tables
    with tempfile.TemporaryDirectory() as directory:
        collector = _metadata_collector(mapping, metadata, Path(directory))
    for (clean_state, clean_municipality), canonical in mapping.items():
        row = {
            'StateName': clean_state,
            'MunicipalityName': clean_municipality,
            'Sex': 'F',
        }
        expected = {'StateName': canonical[0], 'MunicipalityName': canonical[1]}
        expected.update(metadata.get(canonical, {}))
        assert collector.get_data_for_row(row) == expected
    row = {'StateName': unmapped[0], 'MunicipalityName': unmapped[1]}
    assert collector.get_data_for_row(row) == {}


def test_location_keys_collide_when_names_contain_the_key_delimiter(tmp_path):
    """Today the join key is the names joined by "__", so these two locations collide.

    A columnar join would tell them apart. WP-8d decides, and records the change.
    """
    collector = _metadata_collector(
        {
            ('Ash__ford', 'Mill'): ('Northvale', 'Ashford Mill'),
            ('Ash', 'ford__Mill'): ('Southmere', 'Fordmill'),
        },
        {},
        tmp_path,
    )
    first = collector.get_data_for_row(
        {'StateName': 'Ash__ford', 'MunicipalityName': 'Mill'}
    )
    second = collector.get_data_for_row(
        {'StateName': 'Ash', 'MunicipalityName': 'ford__Mill'}
    )
    assert first == second == {'StateName': 'Southmere', 'MunicipalityName': 'Fordmill'}


# Field ids are slugs by the time they reach a BaseRow; the writer does not escape them.
FIELD_IDS = st.text(
    alphabet='abcdefghijklmnopqrstuvwxyz0123456789_', min_size=1, max_size=12
)
VALUES = st.one_of(
    st.integers(min_value=-(10**15), max_value=10**15),
    st.floats(allow_nan=False, allow_infinity=False),
    st.sampled_from([0, 0.0, -0.0]),
)


@PIPELINE_SETTINGS
@given(st.dictionaries(FIELD_IDS, VALUES, min_size=1, max_size=8))
def test_druid_rows_carry_every_value_and_collapse_zeros_into_one_row(data):
    row = BaseRowType(
        {'StateName': 'Northvale', 'Sex': ['F', 'X']}, dict(data), '2021-01-01', 'demo'
    )
    lines = [json.loads(line) for line in row.to_druid_json_iterator()]
    dimensions = {
        'StateName': 'Northvale',
        'Sex': ['F', 'X'],
        'Real_Date': '2021-01-01',
        'source': 'demo',
    }
    nonzero = {field: value for field, value in data.items() if value}
    zero_fields = [field for field, value in data.items() if not value]

    for line in lines:
        assert {
            k: v for k, v in line.items() if k not in ('field', 'val')
        } == dimensions
    written = {line['field']: line['val'] for line in lines if line['val'] != 0}
    assert written == nonzero
    for field, value in written.items():
        assert type(value) is type(nonzero[field])

    zero_lines = [line for line in lines if line['val'] == 0]
    if not zero_fields:
        assert not zero_lines
    else:
        assert len(zero_lines) == 1
        assert type(zero_lines[0]['val']) is int
        expected_field = zero_fields[0] if len(zero_fields) == 1 else zero_fields
        assert zero_lines[0]['field'] == expected_field


TALL_ROWS = st.lists(
    st.tuples(
        st.sampled_from(['Northvale', 'Southmere']),
        st.sampled_from(['Ashford', '']),
        st.sampled_from(['2021-01-01', '2021-01-02']),
        st.sampled_from(['Malaria Positive', 'Bed Nets']),
        st.one_of(st.integers(min_value=-1000, max_value=1000).map(str), st.just('')),
    ),
    max_size=25,
)
SLUGS = {'Malaria Positive': 'demo_malaria_positive', 'Bed Nets': 'demo_bed_nets'}


def _run_aggregator(rows, directory: Path) -> tuple[list[dict], list[str], list[dict]]:
    input_path = directory / 'input.csv'
    _write_csv(
        input_path,
        ['StateName', 'MunicipalityName', 'Date', 'field', 'val'],
        [list(r) for r in rows],
    )
    aggregator = Aggregator(
        datecol='Date',
        source='demo',
        output_field_prefix='demo',
        dimensions=['StateName', 'MunicipalityName'],
    )
    aggregator.process(
        str(input_path),
        str(directory / 'rows.json.lz4'),
        str(directory / 'locations.csv'),
        str(directory / 'fields.csv'),
        None,
    )
    out = subprocess.run(
        ['lz4cat', str(directory / 'rows.json.lz4')],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    with open(directory / 'locations.csv', newline='') as handle:
        locations = list(csv.DictReader(handle))
    fields = (directory / 'fields.csv').read_text().split()
    return [json.loads(line) for line in out.splitlines()], fields, locations


@PIPELINE_SETTINGS
@given(TALL_ROWS)
def test_rollup_sums_each_field_per_dimensions_and_date(rows):
    """Oracle: a row per (dimensions, date) with any value, holding per-field sums."""
    expected: dict[tuple[str, str, str], dict[str, int]] = defaultdict(dict)
    for state, municipality, date, field, value in rows:
        if value:
            slug = SLUGS[field]
            group = expected[(state, municipality, date)]
            group[slug] = group.get(slug, 0) + int(value)

    with tempfile.TemporaryDirectory() as directory:
        output, fields, locations = _run_aggregator(rows, Path(directory))

    actual: dict[tuple[str, str, str], dict[str, int]] = {}
    for row in output:
        key = (
            row['key']['StateName'],
            row['key']['MunicipalityName'],
            row['Real_Date'],
        )
        assert key not in actual, 'rollup must emit one row per dimensions and date'
        assert row['source'] == 'demo'
        actual[key] = row['data']
    assert actual == dict(expected)
    assert fields == sorted({slug for data in expected.values() for slug in data})
    assert {(loc['RawStateName'], loc['RawMunicipalityName']) for loc in locations} == {
        key[:2] for key in expected
    }
