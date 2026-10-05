import type { Locator, Page, Response } from '@playwright/test';

import {
  CASES,
  DEATHS,
  MONTH,
  STATE,
  buildQuery,
  resultContainer,
  selectVisualization,
} from '../support/aqt';
import type { QuerySetup } from '../support/aqt';
import { expect, test } from '../support/fixtures';
import { serveMapAssetsLocally } from '../support/map';

type VizCase = QuerySetup & {
  type: string;
  // The query endpoint the visualization's query engine posts to.
  endpoint: string;
  // An element that only exists once the chart has drawn the e2e Druid's
  // rows: a state the broker reports, a month in its range, or data marks.
  drawn: (viz: Locator) => Locator;
};

const ONE = [CASES];
const TWO = [CASES, DEATHS];

// A state from the broker's location table (tests/golden/synth.py).
const stateLabel = (viz: Locator): Locator => viz.getByText('Acre', { exact: true }).first();
// The first month of the broker's 2014-2024 time boundary.
const firstMonth = (viz: Locator): Locator => viz.getByText(/Jan 2014/).first();
const mapCanvas = (viz: Locator): Locator => viz.locator('canvas.mapboxgl-canvas');
const animationStart = (viz: Locator): Locator => viz.getByText('Jan 2014', { exact: true });
const primaryNumber = (viz: Locator): Locator =>
  viz.locator('.primary-number-value').getByText(/^\d/);

// Every type the visualization picker offers, each with the smallest query
// that meets its requirements (VISUALIZATION_REQUIREMENTS in
// web/client/models/AdvancedQueryApp/VisualizationType/registry.js). The bar
// variants the picker hides (horizontal, bar and line) are BAR with settings.
const CASES_BY_TYPE: VizCase[] = [
  { type: 'TABLE', endpoint: 'table', indicators: ONE, groups: [STATE], drawn: stateLabel },
  {
    type: 'TABLE_SCORECARD',
    endpoint: 'table',
    indicators: ONE,
    groups: [STATE],
    drawn: stateLabel,
  },
  { type: 'BAR', endpoint: 'bar_graph', indicators: ONE, groups: [STATE], drawn: stateLabel },
  {
    type: 'BAR_STACKED',
    endpoint: 'bar_graph',
    indicators: TWO,
    groups: [STATE],
    drawn: stateLabel,
  },
  {
    type: 'BAR_OVERLAPPING',
    endpoint: 'bar_graph',
    indicators: TWO,
    groups: [STATE],
    drawn: stateLabel,
  },
  { type: 'LINE', endpoint: 'line_graph', indicators: ONE, groups: [MONTH], drawn: firstMonth },
  {
    type: 'RANKING',
    endpoint: 'line_graph',
    indicators: ONE,
    groups: [STATE, MONTH],
    drawn: stateLabel,
  },
  {
    type: 'HEATTILES',
    endpoint: 'line_graph',
    indicators: ONE,
    groups: [MONTH],
    drawn: firstMonth,
  },
  {
    type: 'EPICURVE',
    endpoint: 'bar_graph',
    indicators: ONE,
    groups: [MONTH],
    drawn: firstMonth,
  },
  { type: 'MAP', endpoint: 'map', indicators: ONE, groups: [STATE], drawn: mapCanvas },
  { type: 'MAP_HEATMAP', endpoint: 'map', indicators: ONE, groups: [STATE], drawn: mapCanvas },
  {
    type: 'MAP_ANIMATED',
    endpoint: 'map',
    indicators: ONE,
    groups: [STATE, MONTH],
    drawn: animationStart,
  },
  {
    type: 'MAP_HEATMAP_ANIMATED',
    endpoint: 'map',
    indicators: ONE,
    groups: [STATE, MONTH],
    drawn: animationStart,
  },
  {
    type: 'BOXPLOT',
    endpoint: 'bar_graph',
    indicators: ONE,
    groups: [STATE],
    drawn: stateLabel,
  },
  {
    type: 'SCATTERPLOT',
    endpoint: 'bar_graph',
    indicators: TWO,
    groups: [STATE],
    // One bubble per state.
    drawn: viz => viz.locator('.bubblechart-viz .point').nth(2),
  },
  {
    type: 'PIE',
    endpoint: 'hierarchy',
    indicators: ONE,
    groups: [STATE],
    drawn: viz => viz.locator('.ui-pie-chart-pie path').first(),
  },
  {
    type: 'SUNBURST',
    endpoint: 'hierarchy',
    indicators: ONE,
    groups: [STATE],
    // The centre plus one arc per state.
    drawn: viz => viz.locator('.sunburst path').nth(3),
  },
  {
    type: 'HIERARCHY',
    endpoint: 'hierarchy',
    indicators: ONE,
    groups: [STATE],
    drawn: viz => viz.getByText(/^Acre \(\d+\)$/),
  },
  {
    type: 'NUMBER_TREND',
    endpoint: 'hierarchy',
    indicators: ONE,
    groups: [],
    drawn: primaryNumber,
  },
  {
    type: 'NUMBER_TREND_SPARK_LINE',
    endpoint: 'hierarchy',
    indicators: ONE,
    groups: [MONTH],
    drawn: primaryNumber,
  },
];

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
