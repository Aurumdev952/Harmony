import type { Page } from '@playwright/test';

import type { AppErrors } from './fixtures';

// The map loads two things from outside the deployment: the Mapbox base style
// and harmony_demo's boundary GeoJSON (MAP_GEOJSON_LOCATION in
// config/harmony_demo/ui.py). The suite answers both locally, so a map
// renders its data layers on a plain background without leaving the stack.
const BLANK_STYLE = {
  layers: [{ id: 'background', paint: { 'background-color': '#eef1f4' }, type: 'background' }],
  sources: {},
  version: 8,
};

// A square around each state the e2e Druid reports (the LOCATIONS table in
// tests/golden/synth.py), keyed the way the shape layer joins rows to
// features (StateName).
const STATES: [string, number, number][] = [
  ['Acre', -9.128693, -71.973581],
  ['Pará', -3.974166, -52.751945],
  ['Roraima', 1.989233, -61.330109],
];
const BOUNDARIES = {
  features: STATES.map(([name, lat, lon]) => ({
    geometry: {
      coordinates: [
        [
          [lon - 2, lat - 2],
          [lon + 2, lat - 2],
          [lon + 2, lat + 2],
          [lon - 2, lat + 2],
          [lon - 2, lat - 2],
        ],
      ],
      type: 'Polygon',
    },
    properties: { StateName: name },
    type: 'Feature',
  })),
  type: 'FeatureCollection',
};

// Mapbox GL also reports telemetry and a billing session to Mapbox on every
// map load. Production sends these today; the suite blocks them and lets
// them pass with this reason until the MapLibre move (WP-7g) removes them.
const MAPBOX_TELEMETRY: [RegExp, string] = [
  new RegExp(
    '^external request blocked: https://' +
      '(events\\.mapbox\\.com/events/v2|api\\.mapbox\\.com/map-sessions/v1)\\?',
  ),
  'Mapbox GL telemetry and session billing calls; removed by the MapLibre move (WP-7g)',
];

export async function serveMapAssetsLocally(page: Page, appErrors: AppErrors): Promise<void> {
  appErrors.allow(...MAPBOX_TELEMETRY);
  await page.route(/^https:\/\/api\.mapbox\.com\/styles\/v1\//, route =>
    route.fulfill({ json: BLANK_STYLE }),
  );
  await page.route(/^https:\/\/d2ke70b3fbr0dr\.cloudfront\.net\/.*\.geojson$/, route =>
    route.fulfill({ json: BOUNDARIES }),
  );
}
