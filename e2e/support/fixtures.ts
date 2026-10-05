import { expect, test as base } from '@playwright/test';
import type { BrowserContext, Page } from '@playwright/test';

import { BASE_URL } from './env';

type Allowance = { pattern: RegExp; reason: string };

const STACK = new URL(BASE_URL);

/**
 * Collects what a user would experience as breakage: uncaught page errors,
 * 5xx responses and failed requests, in every page of a watched browser
 * context, popups included. It also blocks and records every HTTP request and
 * WebSocket that leaves the disposable stack (CDNs, tile servers, analytics),
 * so the suite never makes an external call. Every test fails at teardown if
 * any were seen, unless the test allowed that exact message with a written
 * reason (a known defect or a limit of the disposable stack).
 */
export class AppErrors {
  readonly seen: string[] = [];

  private readonly allowances: Allowance[] = [];

  /** Starts collecting from a context; the test fixture watches its own. */
  async watchContext(context: BrowserContext): Promise<void> {
    context.pages().forEach(page => this.watchPage(page));
    context.on('page', page => this.watchPage(page));
    await context.route(
      url => url.origin !== STACK.origin && url.protocol.startsWith('http'),
      route => {
        this.seen.push(`external request blocked: ${route.request().url()}`);
        return route.abort('blockedbyclient');
      },
    );
    await context.routeWebSocket(
      url => url.host !== STACK.host,
      ws => {
        this.seen.push(`external websocket blocked: ${ws.url()}`);
        return ws.close();
      },
    );
  }

  private watchPage(page: Page): void {
    page.on('pageerror', error => this.seen.push(`page error: ${error.message}`));
    page.on('response', response => {
      if (response.status() >= 500) {
        const method = response.request().method();
        this.seen.push(`HTTP ${response.status()} ${method} ${response.url()}`);
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

  allow(pattern: RegExp, reason: string): void {
    this.allowances.push({ pattern, reason });
  }

  unexpected(): string[] {
    return this.seen.filter(
      message => !this.allowances.some(({ pattern }) => pattern.test(message)),
    );
  }
}

type Fixtures = {
  appErrors: AppErrors;
  // A page in a new signed-out browser context, watched like `page`.
  signedOutPage: () => Promise<Page>;
};

export const test = base.extend<Fixtures>({
  appErrors: [
    async ({ page }, use) => {
      const errors = new AppErrors();
      await errors.watchContext(page.context());
      await use(errors);
      expect(errors.unexpected(), 'page errors, 5xx responses or failed requests').toEqual([]);
    },
    { auto: true },
  ],
  signedOutPage: async ({ appErrors, browser }, use) => {
    const contexts: BrowserContext[] = [];
    await use(async () => {
      const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
      contexts.push(context);
      await appErrors.watchContext(context);
      return context.newPage();
    });
    await Promise.all(contexts.map(context => context.close()));
  },
});

export { expect };
