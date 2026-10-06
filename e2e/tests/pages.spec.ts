import { SIGNED_OUT } from '../support/auth';
import { LOCALE_PAGES, PAGES, localeCases } from '../support/pages';
import type { PageCase } from '../support/pages';
import { expect, test } from '../support/fixtures';

function pageTest(page: PageCase): void {
  test.describe(page.name, () => {
    if (page.signedOut) {
      test.use({ storageState: SIGNED_OUT });
    }

    test(`${page.path} opens`, async ({ appErrors, page: browser }) => {
      page.knownErrors?.forEach(({ pattern, reason, times }) =>
        appErrors.allow(pattern, reason, times),
      );

      const response = await browser.goto(page.path);

      expect(response?.status()).toBe(page.status ?? 200);
      await expect(page.ready(browser)).toBeVisible();
      const { hash, pathname } = new URL(browser.url());
      expect(`${pathname}${hash}`).toMatch(page.lands);
    });
  });
}

test.describe('every page opens under its legacy URL @smoke @pages', () => {
  PAGES.forEach(pageTest);
});

test.describe('locale-prefixed URLs resolve @smoke @pages', () => {
  localeCases('en').forEach(pageTest);
});

test.describe('pages render in each locale @smoke @pages @i18n', () => {
  LOCALE_PAGES.forEach(pageTest);
});

test.describe('data catalog field pages @smoke @pages', () => {
  test('a field link from the catalog opens, and its URL loads directly', async ({ page }) => {
    await page.goto('/data-catalog');
    await page.getByText('Yellow Fever', { exact: true }).first().click();
    await page.getByText('Yellow Fever Cases', { exact: true }).first().click();
    await expect(page).toHaveURL(/\/data-catalog\/field\/yellow-fever-cases--/);
    const fieldUrl = page.url();

    await page.goto('/overview');
    const response = await page.goto(fieldUrl);

    expect(response?.status()).toBe(200);
    await expect(page.getByText('Yellow Fever Cases', { exact: true }).first()).toBeVisible();
  });
});
