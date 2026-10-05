'''The native replacement for the `epi_week_of_year` JavaScript extraction.

`WHO_EPI_WEEK_EXTRACTION_FORMULA` (scripts/druid/null_audit/legacy_js.py) maps
a timestamp to `2999-12-30T00:00:00.000Z` plus seven days per epi week, where the
epi year starts on the Monday of the week holding 4 January (the ISO week year
start). It counts from the calendar year's start, except that 29 to 31 December
count from the next year's start once they reach it. So 1 to 3 January that
still sit in the previous ISO week year come out as week -1, not 52 or 53.

That value depends only on the month and the ISO week number, so a `timeFormat`
extraction to `MM-ww` cascaded into an inline map lookup reproduces it with no
JavaScript. The map holds every (month, ISO week) pair the Gregorian calendar
can produce; the calendar repeats every 400 years, so one cycle enumerates them.
'''

from datetime import date, datetime, timedelta, timezone
from typing import Dict

_OUTPUT_EPOCH = datetime(2999, 12, 30, tzinfo=timezone.utc)
_CYCLE_START = date(2000, 1, 1)
_CYCLE_DAYS = (date(2400, 1, 1) - _CYCLE_START).days


def js_epi_week_of_year(day: date) -> str:
    '''A line-by-line port of WHO_EPI_WEEK_EXTRACTION_FORMULA in a UTC JVM.'''

    def epi_year_start(year: int) -> date:
        jan_4 = date(year, 1, 4)
        js_day = (jan_4.weekday() + 1) % 7
        offset = 6 if js_day == 0 else js_day - 1
        return jan_4 - timedelta(days=offset)

    start = epi_year_start(day.year)
    if day.month == 12 and day.day >= 29:
        next_start = epi_year_start(day.year + 1)
        if day >= next_start:
            start = next_start
    epi_week = (day - start).days // 7
    output = _OUTPUT_EPOCH + timedelta(days=7 * epi_week)
    return output.strftime('%Y-%m-%dT%H:%M:%S.000Z')


def month_week_key(day: date) -> str:
    '''What the Joda pattern `MM-ww` renders for `day` in UTC.'''
    return f'{day.month:02d}-{day.isocalendar()[1]:02d}'


def epi_week_map() -> Dict[str, str]:
    output: Dict[str, str] = {}
    for offset in range(_CYCLE_DAYS):
        day = _CYCLE_START + timedelta(days=offset)
        output.setdefault(month_week_key(day), js_epi_week_of_year(day))
    return dict(sorted(output.items()))


def epi_week_of_year_extraction() -> dict:
    '''The native extraction function, as Druid receives it.'''
    return {
        'type': 'cascade',
        'extractionFns': [
            {
                'type': 'timeFormat',
                'format': 'MM-ww',
                'timeZone': 'UTC',
                'locale': 'en',
            },
            {
                'type': 'lookup',
                'lookup': {'type': 'map', 'map': epi_week_map()},
                'retainMissingValue': False,
                'replaceMissingValueWith': None,
                'injective': False,
            },
        ],
    }
