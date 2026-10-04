from datetime import date, timedelta

import pytest

from tests.druid.epi_week import (
    epi_week_map,
    epi_week_of_year_extraction,
    js_epi_week_of_year,
    month_week_key,
)


@pytest.mark.parametrize(
    ('day', 'expected'),
    [
        # 2021-01-04 is the Monday that starts WHO epi year 2021: week 0.
        (date(2021, 1, 4), '2999-12-30T00:00:00.000Z'),
        (date(2021, 1, 10), '2999-12-30T00:00:00.000Z'),
        (date(2021, 1, 11), '3000-01-06T00:00:00.000Z'),
        # 1 to 3 January 2021 sit in ISO week 53 of 2020: the formula says -1.
        (date(2021, 1, 1), '2999-12-23T00:00:00.000Z'),
        # 2024-12-30 is in ISO week 1 of 2025: the formula restarts at 0.
        (date(2024, 12, 30), '2999-12-30T00:00:00.000Z'),
        # 2020-12-31 is in ISO week 53 of 2020: week 52.
        (date(2020, 12, 31), '3000-12-29T00:00:00.000Z'),
    ],
)
def test_js_port_matches_hand_worked_dates(day, expected):
    assert js_epi_week_of_year(day) == expected


def test_map_reproduces_the_formula_on_every_day_of_a_gregorian_cycle():
    mapping = epi_week_map()
    start = date(1900, 1, 1)
    for offset in range((date(2400, 1, 1) - start).days):
        day = start + timedelta(days=offset)
        assert mapping[month_week_key(day)] == js_epi_week_of_year(day), day


def test_extraction_has_no_javascript():
    assert 'javascript' not in repr(epi_week_of_year_extraction()).lower()


def test_builder_emits_the_native_extraction():
    from data.query.models.granularity.granularity_extraction import (
        GranularityExtraction,
    )

    built = GranularityExtraction.EXTRACTION_MAP['epi_week_of_year'].build()
    assert built == epi_week_of_year_extraction()
