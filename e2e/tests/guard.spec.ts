import { expect, test } from '@playwright/test';

import { BASE_URL } from '../support/env';
import { AppErrors } from '../support/fixtures';

// Positive controls for the guard every other test relies on: what leaves the
// stack, or breaks, in any page of a watched context is recorded.
test.describe('the external-request guard @smoke @guard', () => {
  test('watches every page of the context, and WebSockets', async ({ browser }) => {
    const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    const errors = new AppErrors();
    await errors.watchContext(context);
    const page = await context.newPage();
    await page.goto(`${BASE_URL}/login`);

    const [popup] = await Promise.all([
      context.waitForEvent('page'),
      page.evaluate(() => {
        window.open('/login');
      }),
    ]);
    await popup.waitForLoadState();
    await popup.evaluate(() => fetch('https://guard-check.invalid/x').catch(() => undefined));
    await popup.evaluate(() => {
      setTimeout(() => {
        throw new Error('guard-check popup error');
      });
    });
    await page.evaluate(() => {
      // eslint-disable-next-line no-new
      new WebSocket('wss://guard-check.invalid/socket');
    });

    await expect
      .poll(() => errors.seen)
      .toEqual(
        expect.arrayContaining([
          'external request blocked: https://guard-check.invalid/x',
          'page error: guard-check popup error',
          'external websocket blocked: wss://guard-check.invalid/socket',
        ]),
      );
    await context.close();
  });

  // A worker's own fetches would pass the context routes above. With
  // serviceWorkers: 'block' (playwright.config.ts) a registration resolves to
  // nothing and no worker starts; allowed, this script would be fetched and
  // installed.
  test('service workers cannot register', async ({ page }) => {
    await page.goto('/login');
    const registration = await page.evaluate(async () =>
      String(await navigator.serviceWorker.register('/js/vendor/min/jquery-3.6.0.js')),
    );
    expect(registration).toBe('undefined');
  });
});
