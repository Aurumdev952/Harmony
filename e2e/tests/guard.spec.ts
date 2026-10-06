import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

import { BASE_URL } from '../support/env';
import { AppErrors } from '../support/fixtures';

// Positive controls for the guard every other test relies on: what leaves the
// stack, or breaks, in any page of a watched context is recorded.
test.describe('the external-request guard @smoke @guard', () => {
  test('an allowance with a count admits that many matches and no more', () => {
    const errors = new AppErrors();
    errors.allow(/^page error: l$/, 'known, once', 1);
    errors.allow(/^HTTP 500 GET /, 'known');
    errors.seen.push('page error: l', 'HTTP 500 GET a', 'page error: l', 'HTTP 500 GET b');
    expect(errors.unexpected()).toEqual(['page error: l']);
  });

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

  // A worker's own fetches would pass the context routes above, so
  // playwright.config.ts sets serviceWorkers: 'block'. The worker script is the
  // CSS entry's JavaScript, which webpack emits empty and so is valid in worker
  // scope; it has to come from the stack, because a worker's script fetch
  // bypasses page routes too. Allowed, it registers (the positive control);
  // under the block the registration resolves to nothing.
  const WORKER = '/build/cssBundle.bundle.js';

  async function register(page: Page): Promise<string> {
    await page.goto('/login');
    return page.evaluate(async worker => {
      const registration = await navigator.serviceWorker.register(worker);
      return registration === undefined ? 'nothing' : 'a registration';
    }, WORKER);
  }

  test('service workers cannot register', async ({ page }) => {
    expect(await register(page)).toBe('nothing');
  });

  test.describe('with workers allowed', () => {
    test.use({ serviceWorkers: 'allow' });

    test('the same worker registers (positive control)', async ({ page }) => {
      expect(await register(page)).toBe('a registration');
    });
  });
});
