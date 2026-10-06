import type { Page, Response } from '@playwright/test';

import { buildQuery, resultContainer, selectVisualization } from '../support/aqt';
import { expect, test } from '../support/fixtures';
import { serveMapAssetsLocally } from '../support/map';
import { CASES_BY_TYPE } from '../support/viz';

function queryResponses(page: Page): Response[] {
  const seen: Response[] = [];
  page.on('response', response => {
    if (response.request().method() === 'POST' && response.url().includes('/api2/query/')) {
      seen.push(response);
    }
  });
  return seen;
}

test.describe('one query per visualization type @smoke @viz', () => {
  for (const vizCase of CASES_BY_TYPE) {
    test(vizCase.type, async ({ appErrors, page }) => {
      const responses = queryResponses(page);
      if (vizCase.type.startsWith('MAP')) {
        await serveMapAssetsLocally(page, appErrors);
      }
      await buildQuery(page, vizCase);
      await selectVisualization(page, vizCase.type);

      await expect
        .poll(() =>
          responses
            .filter(r => new URL(r.url()).pathname === `/api2/query/${vizCase.endpoint}`)
            .map(r => r.status()),
        )
        .toContain(200);
      const viz = resultContainer(page).locator('.visualization').first();
      await expect(vizCase.drawn(viz)).toBeVisible();
      await expect(viz.getByText('No data', { exact: true })).toHaveCount(0);
    });
  }
});
