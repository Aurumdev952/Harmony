import { expect, test } from '@playwright/test';

import { acceptedRegressions, nextBaseline } from '../support/a11y';

// The rules for rewriting e2e/a11y/baseline.json, without a browser.
test.describe('a11y baseline updates only shrink @a11y', () => {
  const NONE = new Set<string>();

  test('a lower count replaces the old one, and a fixed rule leaves the entry', () => {
    expect(
      nextBaseline('login', { 'button-name': 1, 'color-contrast': 3 }, { 'color-contrast': 2 }, NONE),
    ).toEqual({ counts: { 'color-contrast': 2 }, refused: [] });
  });

  test('a higher count is refused and the old count kept', () => {
    expect(nextBaseline('login', { 'color-contrast': 1 }, { 'color-contrast': 4 }, NONE)).toEqual({
      counts: { 'color-contrast': 1 },
      refused: ['login: color-contrast 1 -> 4'],
    });
  });

  test('a new rule is refused', () => {
    expect(nextBaseline('admin', {}, { label: 2 }, NONE)).toEqual({
      counts: {},
      refused: ['admin: label 0 -> 2'],
    });
  });

  test('a regression named in the override is written, for that page and rule only', () => {
    const accepted = acceptedRegressions('login:color-contrast');
    expect(
      nextBaseline('login', { 'color-contrast': 1 }, { 'color-contrast': 4, label: 1 }, accepted),
    ).toEqual({ counts: { 'color-contrast': 4 }, refused: ['login: label 0 -> 1'] });
    expect(nextBaseline('admin', { 'color-contrast': 1 }, { 'color-contrast': 4 }, accepted)).toEqual(
      { counts: { 'color-contrast': 1 }, refused: ['admin: color-contrast 1 -> 4'] },
    );
  });

  test('the override lists page:rule pairs, comma separated', () => {
    expect([...acceptedRegressions(' login:label, admin:color-contrast ')]).toEqual([
      'login:label',
      'admin:color-contrast',
    ]);
    expect([...acceptedRegressions(undefined)]).toEqual([]);
    expect(() => acceptedRegressions('login')).toThrow(/page:rule/);
  });
});
