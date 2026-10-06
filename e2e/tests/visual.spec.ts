import type { Locator, Page } from '@playwright/test';

import { buildQuery, resultContainer, selectVisualization } from '../support/aqt';
import { SIGNED_OUT } from '../support/auth';
import { expect, test } from '../support/fixtures';
import { serveMapAssetsLocally } from '../support/map';
import { PAGES, openSettled } from '../support/pages';
import { CASES_BY_TYPE } from '../support/viz';

// The three widths FE-8 names: a phone, a small laptop, a desktop.
const VIEWPORTS = [
  { height: 844, width: 390 },
  { height: 768, width: 1024 },
  { height: 900, width: 1440 },
];

// Regions that change with the day the stack was built or with how often a
// page was opened: the overview's last-visit, created and view-count columns.
const dashboardActivity = (page: Page): Locator[] => [
  page.locator('.overview-page-dashboard-table tbody td:nth-child(n+2):nth-child(-n+4)'),
];
const VOLATILE: Record<string, (page: Page) => Locator[]> = {
  overview: dashboardActivity,
};

test.beforeAll(() => {
  if (!process.env.E2E_VISUAL_IMAGE) {
    throw new Error(
      'the snapshots were rendered in the pinned Playwright image and only match there; ' +
        'run them with e2e/run.sh',
    );
  }
});

test.describe('pages at three widths @visual', () => {
  for (const viewport of VIEWPORTS) {
    test.describe(`${viewport.width} px`, () => {
      test.use({ viewport });

      for (const pageCase of PAGES.filter(({ aliasOf }) => aliasOf === undefined)) {
        test.describe(pageCase.name, () => {
          if (pageCase.signedOut) {
            test.use({ storageState: SIGNED_OUT });
          }

          test(`${pageCase.path} matches its snapshot`, async ({ appErrors, page }) => {
            pageCase.knownErrors?.forEach(({ pattern, reason, times }) =>
              appErrors.allow(pattern, reason, times),
            );
            await openSettled(page, pageCase);
            await expect(page).toHaveScreenshot(`page-${pageCase.name}-${viewport.width}.png`, {
              mask: VOLATILE[pageCase.name]?.(page) ?? [],
            });
          });
        });
      }
    });
  }
});

// Each chart is drawn once at 1440 px from the e2e Druid's fixed rows, then
// captured after a window resize to each width, narrowest first. The first
// draw is not captured: the line chart's tick spacing at 1440 px differed
// between two first draws of the same query, and only a resize settled it.
test.describe('chart types at three widths @visual', () => {
  for (const vizCase of CASES_BY_TYPE) {
    test(vizCase.type, async ({ appErrors, page }) => {
      if (vizCase.type.startsWith('MAP')) {
        await serveMapAssetsLocally(page, appErrors);
      }
      await buildQuery(page, vizCase);
      await selectVisualization(page, vizCase.type);
      const result = resultContainer(page);
      await expect(vizCase.drawn(result.locator('.visualization').first())).toBeVisible();

      for (const viewport of VIEWPORTS) {
        await page.setViewportSize(viewport);
        await expect(result).toHaveScreenshot(`chart-${vizCase.type}-${viewport.width}.png`);
      }
    });
  }
});
