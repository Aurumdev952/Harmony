import { expect, test as base } from '@playwright/test';
import type { Page } from '@playwright/test';

import { BASE_URL } from './env';

type Allowance = { pattern: RegExp; reason: string };

const STACK_ORIGIN = new URL(BASE_URL).origin;

/**
 * Collects what a user would experience as breakage: uncaught page errors,
 * 5xx responses and failed requests. It also blocks and records every request
 * that leaves the disposable stack (CDNs, tile servers, analytics), so the
 * suite never makes an external call. Every test fails at teardown if any were
 * seen, unless the test allowed that exact message with a written reason
 * (a known defect or a limit of the disposable stack).
 */
export class AppErrors {
  readonly seen: string[] = [];

  private readonly allowances: Allowance[] = [];

  constructor(page: Page) {
    page.on('pageerror', error => this.seen.push(`page error: ${error.message}`));
    page.on('response', response => {
      if (response.status() >= 500) {
        this.seen.push(`HTTP ${response.status()} ${response.request().method()} ${response.url()}`);
      }
    });
    page.on('requestfailed', request => {
      const failure = request.failure()?.errorText ?? '';
      // Navigation away cancels in-flight requests; that is not a failure.
      if (!failure.includes('ERR_ABORTED') && !failure.includes('ERR_BLOCKED_BY_CLIENT')) {
        this.seen.push(`request failed: ${request.method()} ${request.url()} ${failure}`);
      }
    });
  }

  async blockExternalRequests(page: Page): Promise<void> {
    await page.route(
      url => url.origin !== STACK_ORIGIN && url.protocol.startsWith('http'),
      route => {
        this.seen.push(`external request blocked: ${route.request().url()}`);
        return route.abort('blockedbyclient');
      },
    );
  }

  allow(pattern: RegExp, reason: string): void {
    this.allowances.push({ pattern, reason });
  }

  unexpected(): string[] {
    return this.seen.filter(
      message => !this.allowances.some(({ pattern }) => pattern.test(message)),
    );
  }
}

export const test = base.extend<{ appErrors: AppErrors }>({
  appErrors: [
    async ({ page }, use) => {
      const errors = new AppErrors(page);
      await errors.blockExternalRequests(page);
      await use(errors);
      expect(errors.unexpected(), 'page errors, 5xx responses or failed requests').toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
