import { defineConfig, devices } from '@playwright/test';

import { ADMIN_STATE, BASE_URL } from './support/env';

const VISUAL_SPEC = /visual\.spec\.ts$/;
const A11Y_SPEC = /a11y(-baseline)?\.spec\.ts$/;
// run.sh runs each project as its own invocation, in order (see projects
// below), and each keeps its own results and report.
const RUN = process.env.E2E_RUN ?? 'local';

// Start through e2e/run.sh, which brings up the disposable stack and sets the
// E2E_* variables that support/env.ts reads.
export default defineConfig({
  testDir: './tests',
  outputDir: `./test-results/${RUN}`,
  globalSetup: './support/global-setup.ts',
  // The stack runs one gunicorn worker with two threads.
  workers: Number(process.env.E2E_WORKERS ?? 2),
  // A flaky case is a finding, not something to retry away.
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 90_000,
  expect: {
    timeout: 15_000,
    // Re-rendering in the pinned image moves a pixel by at most 2 levels per
    // channel (13 of 120 snapshots differ at all), and 0.05 absorbs that. The
    // default 0.2 also let text change from #313234 to #646567 pass. Any pixel
    // past the threshold fails. (A project-level expect would replace this
    // whole object.)
    toHaveScreenshot: { maxDiffPixels: 0, threshold: 0.05 },
  },
  reporter: [['list'], ['html', { open: 'never', outputFolder: `./report/${RUN}` }]],
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
    // A service worker's requests bypass the context routes the external-
    // request guard relies on. Blocked until WP-7f adds the PWA's worker.
    serviceWorkers: 'block',
  },
  projects: [
    // The axe baseline counts nodes on the stack as seeded; the e2e project
    // adds dashboards, users and sources, so run.sh runs this one before it.
    { name: 'a11y', testMatch: A11Y_SPEC },
    { name: 'e2e', testIgnore: [VISUAL_SPEC, A11Y_SPEC] },
    {
      // Pixels depend on the fonts and libraries of the machine that renders
      // them, so run.sh runs this project in the pinned Playwright image only
      // (tests/visual.spec.ts refuses to run anywhere else).
      name: 'visual',
      testMatch: VISUAL_SPEC,
      snapshotPathTemplate: '{testDir}/../visual/{arg}{ext}',
    },
  ],
});
