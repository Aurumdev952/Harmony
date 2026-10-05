// Dashboard time to last tile for the WP-1a performance baseline (SPEC PERF-7).
// baseline.py runs it (`--dashboards`) and folds its output into the same run;
// it also runs alone:
//
//   eval "$(scripts/perf/stack.sh env)"
//   npm ci --prefix scripts/perf
//   node scripts/perf/dashboards.mjs [--rounds 30] [--warmup 2] [--dashboard SLUG]
//       [--target SIDE=UI_URL ...]
//
// Without --target it loads PERF_CANDIDATE_UI_URL as the side `candidate`.
// With several targets (baseline.py's paired mode passes `reference` and
// `candidate`) every round loads the dashboard once on each, in the order
// given in even rounds and reversed in odd ones, so the sides share the
// host's load.
//
// It makes sure every reference dashboard in dashboards.json exists with that
// specification (created, or patched back to it), then loads each one in
// headless Chromium at 1440 px wide, one load at a time, each in a fresh
// browser context: the HTTP cache is cold and the server's caches are warm
// after the warm-up loads.
//
// Pages open with `?screenshot=1`, the export renderer's view, which renders
// every tile; the normal view lazy-loads tiles as they scroll into sight. A
// load ends at the first animation frame where every query tile shows a
// visualization or the no-results screen and no progress bar is left: the
// test the export renderer uses
// (DashboardScreenshotApp/hooks/useSignalDashboardLoadState.js), without its
// fixed one-second settle and its wait for map basemaps. Every request that
// leaves the stack (Mapbox styles, the GeoJSON CDN) is aborted, so runs never
// depend on the internet; map tiles render their data layer without a basemap.
//
// Prints one JSON line per dashboard and target on stdout:
//   {"case_id", "target", "tiles", "latencies_ms": [...], "bytes": [...], "query_requests": [...]}
// where bytes is everything the page transferred (headers and encoded bodies)
// until the last tile rendered. Progress goes to stderr.

import { readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

import { chromium } from 'playwright';

const HERE = dirname(fileURLToPath(import.meta.url));
const SPECS = JSON.parse(readFileSync(join(HERE, 'dashboards.json'), 'utf8'));
const VIEWPORT = { width: 1440, height: 900 };
const LOAD_TIMEOUT_MS = 600_000;

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set: run eval "$(scripts/perf/stack.sh env)"`,
    );
  }
  return value;
}

// Same rules as baseline.py's read_secret: owned by us, mode 600, NAME=value.
function readSecret(path, name) {
  const info = statSync(path);
  if (info.uid !== process.getuid() || (info.mode & 0o777) !== 0o600) {
    throw new Error(`${path} must be owned by you with mode 600`);
  }
  for (const line of readFileSync(path, 'utf8').split('\n')) {
    const separator = line.indexOf('=');
    if (line.slice(0, separator) === name) return line.slice(separator + 1);
  }
  throw new Error(`${name} not in ${path}`);
}

async function checked(response, what) {
  if (!response.ok()) {
    throw new Error(
      `${what}: HTTP ${response.status()}: ${(await response.text()).slice(
        0,
        500,
      )}`,
    );
  }
  return response.json();
}

// Create the dashboard, or put its specification back to the committed one.
async function ensureDashboard(api, slug, specification) {
  const where = encodeURIComponent(JSON.stringify({ slug }));
  const found = await checked(
    await api.get(`/api2/dashboard?where=${where}`),
    `find ${slug}`,
  );
  if (found.length === 0) {
    await checked(
      await api.post('/api2/dashboard', { data: { slug, specification } }),
      `create ${slug}`,
    );
    return 'created';
  }
  await checked(
    await api.patch(found[0].$uri, { data: { specification } }),
    `update ${slug}`,
  );
  return 'updated';
}

// Runs in the page; resolves with performance.now(), milliseconds since
// navigation start, at the first frame where every query tile has rendered.
function waitForLastTile(expectedTiles) {
  return new Promise(resolve => {
    const rendered = () => {
      if (document.querySelector('.visualization-container .progress'))
        return false;
      const noData = document.querySelectorAll(
        '.visualization-container > .no-results-screen',
      );
      const withData = document.querySelectorAll(
        '.visualization-container .visualization',
      );
      return noData.length + withData.length >= expectedTiles;
    };
    const tick = () =>
      rendered() ? resolve(performance.now()) : requestAnimationFrame(tick);
    tick();
  });
}

async function loadOnce(browser, baseUrl, storageState, slug, tiles) {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    storageState,
  });
  try {
    await context.route(
      url => url.origin !== baseUrl,
      route => route.abort(),
    );
    const page = await context.newPage();
    const finished = [];
    let queryRequests = 0;
    page.on('requestfinished', request => {
      finished.push(
        request.sizes().then(s => s.responseHeadersSize + s.responseBodySize),
      );
      if (new URL(request.url()).pathname.startsWith('/api2/query/'))
        queryRequests += 1;
    });
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.setDefaultTimeout(LOAD_TIMEOUT_MS);
    await page.goto(`${baseUrl}/dashboard/${slug}?screenshot=1`, {
      waitUntil: 'commit',
    });
    const lastTileMs = await page.evaluate(waitForLastTile, tiles);
    // Requests finished by now are the ones the last tile waited on.
    const sizes = await Promise.all(finished);
    if (errors.length) {
      throw new Error(
        `${slug}: page errors: ${errors.join('; ').slice(0, 500)}`,
      );
    }
    return {
      ms: lastTileMs,
      bytes: sizes.reduce((a, b) => a + b, 0),
      queryRequests,
    };
  } finally {
    await context.close();
  }
}

function parseTargets(specs) {
  if (!specs) {
    return [{ side: 'candidate', url: requireEnv('PERF_CANDIDATE_UI_URL') }];
  }
  return specs.map(spec => {
    const separator = spec.indexOf('=');
    if (separator < 1) throw new Error(`--target ${spec}: expected SIDE=URL`);
    return { side: spec.slice(0, separator), url: spec.slice(separator + 1) };
  });
}

async function logIn(browser, url, password) {
  const context = await browser.newContext({ baseURL: url });
  const response = await context.request.post(
    '/api2/authentication/login?set_cookie=true',
    { data: { email: requireEnv('PERF_USERNAME'), password } },
  );
  await checked(response, `login at ${url}`);
  return context;
}

async function main() {
  const { values } = parseArgs({
    options: {
      rounds: { type: 'string', default: '30' },
      warmup: { type: 'string', default: '2' },
      dashboard: { type: 'string', multiple: true },
      target: { type: 'string', multiple: true },
    },
  });
  const rounds = Number(values.rounds);
  const warmup = Number(values.warmup);
  const password = readSecret(
    requireEnv('PERF_CREDENTIALS_FILE'),
    'PERF_PASSWORD',
  );

  const browser = await chromium.launch();
  try {
    const targets = [];
    for (const { side, url } of parseTargets(values.target)) {
      const origin = new URL(url).origin;
      const context = await logIn(browser, origin, password);
      targets.push({ side, origin, context });
    }

    // Every target shares one database, so the dashboards are set up once.
    const slugs = values.dashboard ?? Object.keys(SPECS);
    for (const slug of slugs) {
      const specification = SPECS[slug];
      if (!specification) throw new Error(`${slug} is not in dashboards.json`);
      process.stderr.write(
        `${slug}: ${await ensureDashboard(
          targets[0].context.request,
          slug,
          specification,
        )}\n`,
      );
    }
    for (const target of targets) {
      target.storageState = await target.context.storageState();
      await target.context.close();
    }

    for (const slug of slugs) {
      const tiles = SPECS[slug].items.filter(
        holder => holder.item.type === 'QUERY_ITEM',
      ).length;
      const results = new Map(
        targets.map(({ side }) => [
          side,
          {
            case_id: slug,
            target: side,
            tiles,
            latencies_ms: [],
            bytes: [],
            query_requests: [],
          },
        ]),
      );
      for (let index = 0; index < warmup + rounds; index += 1) {
        const order = index % 2 === 0 ? targets : [...targets].reverse();
        for (const target of order) {
          const load = await loadOnce(
            browser,
            target.origin,
            target.storageState,
            slug,
            tiles,
          );
          if (index < warmup) continue;
          const result = results.get(target.side);
          result.latencies_ms.push(load.ms);
          result.bytes.push(load.bytes);
          result.query_requests.push(load.queryRequests);
        }
      }
      for (const result of results.values()) {
        process.stderr.write(
          `${slug} ${result.target}: ${result.latencies_ms
            .map(Math.round)
            .join(' ')} ms\n`,
        );
        process.stdout.write(`${JSON.stringify(result)}\n`);
      }
    }
  } finally {
    await browser.close();
  }
}

await main();
