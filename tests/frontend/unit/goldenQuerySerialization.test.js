// The golden suite (tests/golden, WP-2a) pins the QueryRequest payloads the
// backend accepts. Each payload must survive a trip through the client's query
// models unchanged: deserialize it, then serialize it the way a visualization
// does before POSTing. A mismatch means the client would send the backend a
// request the golden suite does not cover.
import path from 'path';
import { describe, expect, test } from 'vitest';

import * as Zen from 'lib/Zen';
import CalculationUtil from 'models/core/wip/Calculation/CalculationUtil';
import GroupingItemUtil from 'models/core/wip/GroupingItem/GroupingItemUtil';
import QueryFilterUtil from 'models/core/wip/QueryFilter/QueryFilterUtil';
import { REPO_ROOT } from './helpers';
import { readdirSync, readFileSync } from 'fs';

const CASES_DIR = path.join(REPO_ROOT, 'tests/golden/cases');

function loadRequest(name) {
  const raw = JSON.parse(
    readFileSync(path.join(CASES_DIR, name, 'request.json'), 'utf8'),
  );
  // Outlier cases wrap the query request (DataQualityService).
  return raw.queryRequest !== undefined ? raw.queryRequest : raw;
}

const CASES = readdirSync(CASES_DIR)
  .sort()
  .map(name => ({ name, request: loadRequest(name) }));

test('the golden suite is present', () => {
  expect(CASES.length).toBeGreaterThanOrEqual(80);
});

test('the golden suite covers every calculation type the client can build', () => {
  const covered = new Set();
  CASES.forEach(({ request }) =>
    request.fields.forEach(field => covered.add(field.calculation.type)),
  );
  expect([...covered].sort()).toStrictEqual([
    'AVERAGE_OVER_TIME',
    'AVG',
    'COMPLEX',
    'COUNT',
    'COUNT_DISTINCT',
    'FORMULA',
    'LAST_VALUE',
    'MAX',
    'MIN',
    'SUM',
    'WINDOW',
  ]);
});

describe.each(CASES)('golden case $name', ({ request }) => {
  test('each field calculation round-trips through the client model', async () => {
    const results = await Promise.all(
      request.fields.map(field =>
        CalculationUtil.deserializeAsync(field.calculation).then(calculation =>
          CalculationUtil.serializeForQuery(calculation, Zen.Array.create()),
        ),
      ),
    );
    expect(results).toStrictEqual(request.fields.map(field => field.calculation));
  });

  test('the query filter round-trips through the client model', async () => {
    if (Object.keys(request.filter).length === 0) {
      return;
    }
    const filter = await QueryFilterUtil.deserializeAsync(request.filter);
    expect(filter.serialize()).toStrictEqual(request.filter);
  });

  test('each group round-trips through the client model', async () => {
    const groups = await Promise.all(
      request.groups.map(group =>
        GroupingItemUtil.deserializeAsync({
          item: { ...group, name: 'display name only' },
          type:
            'granularity' in group ? 'GROUPING_GRANULARITY' : 'GROUPING_DIMENSION',
        }),
      ),
    );
    expect(groups.map(group => group.serializeForQuery())).toStrictEqual(
      request.groups,
    );
  });
});
