"""Invariants of the per-row pipeline code that any reimplementation keeps.

Behaviour that WP-8d may change on purpose lives in ``test_pinned_behaviours.py``.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pipeline_inprocess import BaseRowType, get_date, metadata_collector, run_aggregator

PIPELINE_SETTINGS = settings(database=None, deadline=None)


@pytest.mark.skipif(not os.environ.get('CI'), reason='CI profile only')
def test_ci_draws_the_same_examples_every_run():
    assert PIPELINE_SETTINGS.derandomize


DATES = st.dates(
    min_value=datetime.date(1900, 1, 1), max_value=datetime.date(2099, 12, 31)
)


@PIPELINE_SETTINGS
@given(DATES)
def test_iso_dates_parse_to_themselves(date):
    assert get_date(date.isoformat()) == date.isoformat()


@PIPELINE_SETTINGS
@given(DATES, st.times())
def test_iso_datetimes_keep_their_date(date, time):
    assert (
        get_date(f'{date.isoformat()}T{time.strftime("%H:%M:%S")}') == date.isoformat()
    )


# Names never contain "__", the join-key delimiter (see test_pinned_behaviours).
LOCATION_NAMES = st.text(
    alphabet=st.characters(blacklist_categories=('Cs', 'Cc'), blacklist_characters='_'),
    min_size=1,
    max_size=8,
)
CLEAN_KEYS = st.tuples(LOCATION_NAMES, st.one_of(st.just(''), LOCATION_NAMES))
CANONICAL_KEYS = st.tuples(LOCATION_NAMES, LOCATION_NAMES)
METADATA_COLUMNS = ('StateID', 'MunicipalityID', 'MunicipalityLat', 'MunicipalityLon')


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
        collector = metadata_collector(
            mapping, metadata, METADATA_COLUMNS, Path(directory)
        )
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
def test_druid_rows_carry_every_value_once_and_collapse_zeros_into_one_row(data):
    dimensions = {'StateName': 'Northvale', 'Sex': ['F', 'X']}
    row = BaseRowType(dict(dimensions), dict(data), '2021-01-01', 'demo')
    lines = [json.loads(line) for line in row.to_druid_json_iterator()]
    nonzero = {field: value for field, value in data.items() if value}
    zero_fields = [field for field, value in data.items() if not value]

    assert len(lines) == len(nonzero) + (1 if zero_fields else 0)
    for line in lines:
        assert {k: v for k, v in line.items() if k not in ('field', 'val')} == {
            **dimensions,
            'Real_Date': '2021-01-01',
            'source': 'demo',
        }
    written = {line['field']: line['val'] for line in lines if line['val'] != 0}
    assert written == nonzero
    for field, value in written.items():
        assert type(value) is type(nonzero[field])

    zero_lines = [line for line in lines if line['val'] == 0]
    if zero_fields:
        assert type(zero_lines[0]['val']) is int
        expected_field = zero_fields[0] if len(zero_fields) == 1 else zero_fields
        assert zero_lines[0]['field'] == expected_field


TALL_HEADER = ['StateName', 'MunicipalityName', 'Date', 'field', 'val']
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
        output, fields, locations = run_aggregator(
            TALL_HEADER,
            [list(row) for row in rows],
            Path(directory),
            dimensions=['StateName', 'MunicipalityName'],
        )

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
