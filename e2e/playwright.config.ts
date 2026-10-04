import { defineConfig, devices } from '@playwright/test';

import { ADMIN_STATE, BASE_URL } from './support/env';

// Start through e2e/run.sh, which brings up the disposable stack and sets the
// E2E_* variables that support/env.ts reads.
export default defineConfig({
  testDir: './tests',
  outputDir: './test-results',
  globalSetup: './support/global-setup.ts',
  // The stack runs one gunicorn worker with two threads.
  workers: Number(process.env.E2E_WORKERS ?? 2),
  // A flaky case is a finding, not something to retry away.
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: './report' }]],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: BASE_URL,
    storageState: ADMIN_STATE,
    viewport: { height: 900, width: 1440 },
    locale: 'en-US',
    timezoneId: 'UTC',
    screenshot: 'only-on-failure',
    // Traces record typed text; specs that type a password turn them off.
    trace: 'retain-on-failure',
  },
});
