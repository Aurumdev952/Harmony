// Date utilities, including the Ethiopian calendar (SPEC INV-5). The
// Ethiopian checks enumerate every day from 1990 to 2040 instead of sampling:
// the calendar has a 4-year leap cycle and a 13th month of 5 or 6 days, and an
// exhaustive walk covers every boundary deterministically.
import { afterAll, describe, expect, test } from 'vitest';

import Moment from 'models/core/wip/DateTime/Moment';
import {
  DATE_FORMAT,
  ETHIOPIAN_MONTHS,
  formatDate,
  formatDateByGranularity,
  formatDatesByGranularity,
  getEthiopianDateLabel,
  momentToEthiopian,
  toGregorianEndDate,
  toGregorianStartDate,
  toGregorianWithZeroIndexedMonth,
} from 'util/dateUtil';
import { DEFAULT_BACKEND, withBackend } from './helpers';

const FIRST_DAY = Moment.utc('1990-01-01');
const LAST_DAY = Moment.utc('2040-12-31');

function everyDay() {
  const days = [];
  for (let day = FIRST_DAY; !day.isAfter(LAST_DAY); day = day.add(1, 'day')) {
    days.push(day);
  }
  return days;
}

const DAYS = everyDay();

function isEthiopianLeapYear(year) {
  return year % 4 === 3;
}

afterAll(() => {
  window.__JSON_FROM_BACKEND = structuredClone(DEFAULT_BACKEND);
});

describe('Ethiopian calendar conversion', () => {
  test('known anchors: Enkutatash and Pagume', () => {
    // 2016 E.C. starts on 12 September 2023 because 2015 E.C. is a leap year
    // with a 6-day Pagume; 2017 E.C. starts on 11 September 2024.
    expect(momentToEthiopian(Moment.utc('2023-09-12'), false)).toEqual([2016, 1, 1]);
    expect(momentToEthiopian(Moment.utc('2024-09-11'), false)).toEqual([2017, 1, 1]);
    expect(momentToEthiopian(Moment.utc('2023-09-11'), false)).toEqual([2015, 13, 6]);
    expect(momentToEthiopian(Moment.utc('2024-09-10'), false)).toEqual([2016, 13, 5]);
    expect(momentToEthiopian(Moment.utc('2024-01-07'), false)).toEqual([2016, 4, 28]);
  });

  test('Pagume is reported as Meskerem of the next year by default', () => {
    expect(momentToEthiopian(Moment.utc('2023-09-11'))).toEqual([2016, 1, 6]);
    expect(momentToEthiopian(Moment.utc('2023-09-06'))).toEqual([2016, 1, 1]);
    expect(momentToEthiopian(Moment.utc('2023-09-05'))).toEqual([2015, 12, 30]);
  });

  test('every day from 1990 to 2040 converts to Ethiopian and back to itself', () => {
    const mismatches = DAYS.filter(day => {
      const [year, month, date] = momentToEthiopian(day, false);
      const [gYear, gMonth, gDate] = toGregorianWithZeroIndexedMonth(year, month - 1, date);
      return gYear !== day.year() || gMonth !== day.month() || gDate !== day.date();
    }).map(day => day.format(DATE_FORMAT));

    expect(DAYS.length).toBe(18628);
    expect(mismatches).toEqual([]);
  });

  test('consecutive days are consecutive Ethiopian dates with valid month lengths', () => {
    const violations = [];
    for (let i = 1; i < DAYS.length; i += 1) {
      const [py, pm, pd] = momentToEthiopian(DAYS[i - 1], false);
      const [y, m, d] = momentToEthiopian(DAYS[i], false);
      const pagumeLength = isEthiopianLeapYear(py) ? 6 : 5;
      const monthLength = pm === 13 ? pagumeLength : 30;
      let expected;
      if (pd < monthLength) {
        expected = [py, pm, pd + 1];
      } else if (pm < 13) {
        expected = [py, pm + 1, 1];
      } else {
        expected = [py + 1, 1, 1];
      }
      if (y !== expected[0] || m !== expected[1] || d !== expected[2]) {
        violations.push(`${DAYS[i].format(DATE_FORMAT)}: ${[y, m, d]} after ${[py, pm, pd]}`);
      }
    }
    expect(violations).toEqual([]);
  });

  test('ET date range helpers start at day 1 and end at the next month', () => {
    expect(toGregorianStartDate({ month: 0, year: 2016 })).toEqual([2023, 8, 12]);
    expect(toGregorianEndDate({ month: 0, year: 2016 })).toEqual([2023, 9, 12]);
    // The last index (Pagume) rolls over to Meskerem 1 of the next year.
    expect(toGregorianEndDate({ month: 12, year: 2015 })).toEqual([2023, 8, 12]);
  });
});

describe('Ethiopian date labels', () => {
  test('the 13 month names are in calendar order', () => {
    expect(ETHIOPIAN_MONTHS).toEqual([
      'Meskerem', 'Tikemet', 'Hidar', 'Tahesas', 'Tir', 'Yekatit', 'Megabit',
      'Miazia', 'Genbot', 'Sene', 'Hamle', 'Nehase', 'Pagume',
    ]);
  });

  test('labels drop the day on the first of the month and honour exclusions', () => {
    expect(getEthiopianDateLabel(Moment.utc('2023-09-12'))).toBe('Mes 2016');
    expect(getEthiopianDateLabel(Moment.utc('2024-01-07'))).toBe('28 Tah 2016');
    expect(getEthiopianDateLabel(Moment.utc('2024-01-07'), true, true)).toBe('Tah 2016');
    expect(getEthiopianDateLabel(Moment.utc('2024-01-07'), true, false, true)).toBe('28 2016');
    expect(getEthiopianDateLabel(Moment.utc('2024-01-07'), true, false, false, true)).toBe('28 Tah');
    expect(getEthiopianDateLabel(Moment.utc('2023-09-11'), false)).toBe('6 Pag 2015');
  });
});

describe('Gregorian formatting without calendar settings', () => {
  test('formatDate applies a moment format to a UTC date string', () => {
    expect(formatDate('2024-03-01', 'MMM YYYY')).toBe('Mar 2024');
    expect(formatDate('2024-03-01T00:00:00.000Z', DATE_FORMAT)).toBe('2024-03-01');
  });

  test('without calendar settings every granularity falls back to YYYY-MM-DD', () => {
    expect(formatDateByGranularity('2024-03-01', 'month', true)).toBe('2024-03-01');
    expect(formatDateByGranularity('2024-03-01', 'year', false)).toBe('2024-03-01');
  });

  test('stat_month labels the month that follows the bucket start', () => {
    expect(formatDateByGranularity('2024-02-21', 'stat_month', false)).toBe('2024-03-21');
  });
});

describe('Ethiopian deployments (enableEtDateSelection)', () => {
  test('dates render on the Ethiopian calendar per granularity', async () => {
    const et = await withBackend({ enableEtDateSelection: true }, () =>
      import('util/dateUtil'),
    );

    expect(et.formatDateByGranularity('2024-01-07', 'day', false)).toBe('28 Tah 2016');
    expect(et.formatDateByGranularity('2024-01-07', 'month', false)).toBe('Tah 2016');
    expect(et.formatDateByGranularity('2024-09-11', 'year', false)).toBe('2017');
    expect(et.formatDateByGranularity('2024-01-07', 'month_of_year', false)).toBe('Tah');
    // Pagume is not merged when formatting a bucket date.
    expect(et.formatDateByGranularity('2023-09-11', 'day', false)).toBe('6 Pag 2015');
  });

  test('turning Ethiopian display off for a call keeps the Gregorian date', async () => {
    const et = await withBackend({ enableEtDateSelection: true }, () =>
      import('util/dateUtil'),
    );

    expect(et.formatDateByGranularity('2024-01-07', 'month', false, false)).toBe('2024-01-07');
  });

  test('simplified series show the year only when the Ethiopian year changes', async () => {
    const et = await withBackend({ enableEtDateSelection: true }, () =>
      import('util/dateUtil'),
    );

    expect(
      et.formatDatesByGranularity(
        ['2024-07-08', '2024-08-07', '2024-09-11', '2024-10-11'],
        'month',
        true,
        true,
        true,
      ),
    ).toEqual(['Ham 2016', 'Neh', 'Mes 2017', 'Tik']);
  });

  test('the default ET range is the configured Ethiopian months', async () => {
    const et = await withBackend({ enableEtDateSelection: true }, () =>
      import('util/dateUtil'),
    );

    expect(et.getDefaultDateRange()).toEqual({
      endDate: '2018-07-08',
      startDate: '2017-07-08',
    });
  });
});

test('Gregorian series simplification compares calendar years', () => {
  expect(
    formatDatesByGranularity(['2023-12-01', '2024-01-01', '2024-02-01'], 'month', true, true, true),
  ).toEqual(['2023-12-01', '2024-01-01', '2024-02-01']);
});
