# Phase 1. Performance quick wins on the current stack

Back to [overview](overview.md). Evidence: [02-architecture-deep-dive.md](02-architecture-deep-dive.md).

**Goal.** Win the cheap latency and stability gains now, on Flask, so users feel progress months before the migration lands. Every change here carries over to FastAPI unchanged, because it lives in the query engine and not in the framework.

## 1a. Baseline

- **Changes.** Add `scripts/perf/baseline.py`. It replays a fixed set of `QueryRequest` payloads against `/api2/query/*` and records p50 and p95 latency, response bytes and Druid time. Add a Playwright script that loads three reference dashboards and records time to last tile and bytes transferred.
- **Data structure.** `PerfSample = {case_id, endpoint, p50_ms, p95_ms, bytes, druid_ms}`, written as JSON lines to `docs/modernisation/perf/`.
- **Verification.** Two consecutive runs agree within 10%. The baseline file is committed.

## 1b. Shared result cache

- **Changes.**
  - Add `QueryResultCache` next to `web/server/query/` with get and set.
  - The key is `(datasource_version, sha256(canonical QueryRequest JSON), sha256(policy filter))`.
  - Wrap the bar, line, table, map, hierarchy and data-quality handlers in `web/server/api/query/query_models.py`.
- **Data structure.** `CacheKey = (str datasource_version, str request_hash, str policy_hash)`. The value is the serialised response bytes.
- **Verification.**
  - Unit tests: identical requests from two users with the same policy share an entry. Different policies do not. A new datasource version misses.
  - The baseline shows the hit-path p50 below 50 ms.

## 1c. Columnar parsing

- **Changes.**
  - Build the DataFrame straight from Druid's array rows in `db/druid/query_builder.py:308-466` and `652-750`.
  - Vectorise the timestamp and null fixups and delete the repeated `pd.concat`.
  - Replace the per-date filter in `web/server/query/visualizations/map.py:192` with one `groupby`.
- **Verification.**
  - Golden tests from phase 2a must exist first. If they don't yet, capture golden outputs for 20 recorded queries before changing anything.
  - Outputs are byte-identical.
  - The baseline shows the improvement on the large-table and map cases.

## 1d. Stop runaway work

- **Changes.**
  - Add `timeout=` to `session.post` in `db/druid/query_client.py:75`, plus `context.timeout` on every Druid query.
  - Remove `'reload': True` from `web/gunicorn_server.py:159` outside development.
  - Read `current_db_datasource` once per request into `flask.g` (`web/server/data/druid_context.py:112-114`).
  - Stop calling Druid status from `TemplateRenderer` on every page render (`web/server/util/template_renderer.py:141`). Serve it from a cached value.
- **Verification.**
  - A test query that sleeps past the timeout returns a 504 with a clear message.
  - Pages render while Druid is stopped.

## 1e. Fix the table stream and the outliers flag

- **Changes.**
  - Replace `Thread(...).run()` (`query_models.py:185`) with a generator that yields orjson chunks.
  - Add server-side row limits and pagination parameters to `/query/table`.
  - Fix `include_outliers` at line 266.
- **Verification.**
  - Failing tests first.
  - Peak memory on the largest table case drops, measured with `tracemalloc` in the baseline.
  - The outliers tab shows data.

## 1f. Concurrent sub-queries

- **Changes.** Line graph, bump chart and heat-tile totals (`line_graph.py:52-69`), and the three data-quality queries (`data_quality_report.py:346-350`), run concurrently with `gevent.spawn`. Where the totals can come from the same query through a grouping set, merge them instead.
- **Verification.** Golden outputs are unchanged. The baseline line-graph p50 drops by about a third or more.

## 1g. Front-end payload hygiene

- **Changes.**
  - Delete the eager Plotly tag (`grid_dashboard.html:8`).
  - Mark the remaining vendor scripts `defer`.
  - Name bundles `[name].[contenthash].js`.
  - Have nginx serve `/static/build/` with `Cache-Control: public, max-age=31536000, immutable`.
  - Give the Hasura field catalog an ETag at the Flask proxy.
- **Verification.** The Playwright baseline shows fewer bytes and an earlier first tile on a throttled "Slow 4G" profile. Repeat visits transfer no bundle bytes.

## 1h. Self-hosted export rendering

- **Changes.**
  - Replace urlbox (`web/server/routes/views/page_renderer.py`) with a sandboxed renderer sidecar that drives headless Chromium through Playwright against the existing screenshot route; the Celery task that queues the job arrives with WP-5f (decision 0009).
  - Replace the fixed 10-second delay with a "tiles loaded" signal the screenshot app already knows how to produce.
  - Scope the render JWT to the dashboard being rendered instead of `query_needs: ["*"]`.
- **Data structure.** `RenderJob = {dashboard_id, format: pdf|png, viewport, requested_by, status}`.
- **Verification.** PDF and PNG exports of the three reference dashboards match the urlbox output visually, using Playwright screenshot comparison with a tolerance.
