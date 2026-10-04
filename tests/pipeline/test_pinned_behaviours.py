"""Today's behaviour that a columnar rewrite would change without noticing.

These are not invariants. WP-8d keeps each one, or changes it and records the change
in its WP file with reviewer acceptance (INV-2), updating the test in the same WP.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pipeline_inprocess import get_date, metadata_collector, run_aggregator

DATES = st.dates(
    min_value=datetime.date(1900, 1, 1), max_value=datetime.date(2099, 12, 31)
)


@settings(database=None, deadline=None)
@given(DATES)
def test_slash_dates_are_month_first_unless_the_first_number_exceeds_twelve(date):
    """dateutil reads DD/MM/YYYY as MM/DD/YYYY whenever the day could be a month."""
    text = f'{date.day:02d}/{date.month:02d}/{date.year}'
    expected = date if date.day > 12 else datetime.date(date.year, date.day, date.month)
    assert get_date(text) == expected.isoformat()


@pytest.mark.parametrize(
    ('text', 'year', 'month'),
    [('2020', 2020, None), ('2019-05', 2019, 5), ('May 2018', 2018, 5)],
)
def test_partial_dates_take_missing_parts_from_today(text, year, month):
    """A year-only or month-only date borrows today's month and day."""
    before = datetime.date.today()
    parsed = get_date(text)
    after = datetime.date.today()
    if (before.month, before.day) == (2, 29):
        pytest.skip('today has no equivalent day in other years')
    expected = {
        day.replace(year=year, month=month or day.month).isoformat()
        for day in (before, after)
    }
    assert parsed in expected


def test_location_join_keys_collide_when_names_contain_the_key_delimiter(tmp_path):
    """fill_dimension_data keys the join on names joined by "__"."""
    collector = metadata_collector(
        {
            ('Ash__ford', 'Mill'): ('Northvale', 'Ashford Mill'),
            ('Ash', 'ford__Mill'): ('Southmere', 'Fordmill'),
        },
        {},
        (),
        tmp_path,
    )
    first = collector.get_data_for_row(
        {'StateName': 'Ash__ford', 'MunicipalityName': 'Mill'}
    )
    second = collector.get_data_for_row(
        {'StateName': 'Ash', 'MunicipalityName': 'ford__Mill'}
    )
    assert first == second == {'StateName': 'Southmere', 'MunicipalityName': 'Fordmill'}


def test_rollup_keys_collide_when_names_contain_the_key_delimiter(tmp_path: Path):
    """process_csv keys rollup on raw values joined by "__": two locations merge into
    one base row, and the second never reaches locations.csv."""
    rows, _, locations = run_aggregator(
        ['StateName', 'MunicipalityName', 'Date', 'field', 'val'],
        [
            ['Ash__ford', 'Mill', '2021-01-01', 'Visits', '2'],
            ['Ash', 'ford__Mill', '2021-01-01', 'Visits', '3'],
        ],
        tmp_path,
        dimensions=['StateName', 'MunicipalityName'],
    )
    assert rows == [
        {
            'key': {'StateName': 'Ash__ford', 'MunicipalityName': 'Mill'},
            'data': {'demo_visits': 5},
            'Real_Date': '2021-01-01',
            'source': 'demo',
        }
    ]
    assert [(loc['RawStateName'], loc['RawMunicipalityName']) for loc in locations] == [
        ('Ash__ford', 'Mill')
    ]
