---
name: harmony-query-engine
description: How Harmony turns a user's query into Druid queries and back, and how to change that path safely. Use when touching QueryRequest, calculations, the Druid query builder, query policies, the result cache, visualization shapers, AppContext, settings or config loading, or anything under harmony/core, data/query, db/druid or web/server/query.
---

# Harmony query engine

Every number a ministry analyst sees passes through this path. Correctness beats speed. The golden suite (`tests/golden/`) decides what "unchanged" means.

## The path today

1. **Browser.** A visualization `QueryEngine` posts `querySelections.serializeForQuery()` through `web/client/components/visualizations/common/QueryInterface.js`.
2. **Endpoint.** Potion routes in `web/server/api/query/query_models.py` deserialise with `related.to_model(QueryRequest, ...)` (`web/server/query/request/query_request.py`).
3. **Build.** `QueryRequest.to_druid_query()` produces a `GroupByQueryBuilder` (`db/druid/query_builder.py`):
   - each indicator becomes a filtered aggregator on the `field` dimension (`db/druid/calculations/`);
   - formulas become native `expression` post-aggregators (`data/query/models/calculation/formula_calculation.py`);
   - the OR of all aggregator filters is pushed down as the query filter (`query_builder.py:200-218`), so do not drop it;
   - subtotals use `subtotalsSpec` (`query_builder.py:303`).
4. **Authorise.** `AuthorizedQueryClient.run_query` ANDs in the caller's query-policy filter (`web/server/routes/views/query_policy.py:322-328`). `run_raw_query` does not, and SEC-4 requires fixing that.
5. **Execute.** `db/druid/query_client.py` posts with a pooled `requests.Session` and parses with `ijson`.
6. **Shape.** `web/server/query/visualizations/*` turns rows into each chart's response.

## The data model

The model is tall and narrow: one Druid row per (dimensions, date, source, `field`), with a `val` metric rolled up into `count`, `sum`, `min` and `max` (`config/druid_base.py`).
- An indicator is a filter on `field`, never a column.
- A ratio is a post-aggregation over two filtered sums.
- Zero rows for the same key collapse into one row with a multi-valued `field` (`data/pipeline/datatypes/base_row.py:146-154`). Count-distinct logic must respect this.

## Target shape (SPEC C-1, C-3, C-9)

- `harmony/core/` imports no web framework. An import-linter contract enforces this (BE-1).
- `QueryRequest` and `QueryResponse` become Pydantic v2 models (load `pydantic:pydantic`). Calculations and filters are discriminated unions on a `type` field. The JSON Schema is published in OpenAPI and must stay backward compatible with stored specs.
- `QueryResponse` is columnar: `{columns, rows, totals?, meta}`.
- The cache key is `(datasource_version, sha256(canonical request JSON), sha256(policy filter))`.
  - Canonical JSON means sorted keys, no whitespace, and floats rendered stably.
  - Never key on user id. Two users with the same policy share entries.
- `AppContext` (frozen dataclass) holds settings, deployment, database, Druid client, datasource registry, cache and mailer. Pass it explicitly. Never reach for a global.
- `Principal` is computed once per request and passed to every policy function.

## Rules for changes

- **Golden first.** Before changing builder or shaping code, make sure a golden case covers the visualization and calculation types you touch. If one is missing, ask QA through the protocol, or add it in `tests/golden/` via a request to `qa`.
- **Columns, not rows.** Build frames from Druid's array rows (`pd.DataFrame(rows, columns=header)`, or Polars). Never build one dict per row.
- **Every Druid call has two timeouts:** the client timeout and `context.timeout` (PERF-2).
- **Run independent sub-queries concurrently.** Totals and the main query, and data-quality parts, go through `asyncio.gather` on FastAPI or `gevent.spawn` on Flask.
- **Do not change result semantics silently.** If an output changes, record the before and after in the WP file and get reviewer acceptance (INV-2).
- **Policy on every path.** Any new execution path must take a `Principal` and apply its filter (SEC-4).
- **No I/O at import time.** Deployment modules (`config/<code>/*.py`) are loaded once through `harmony.core.deployment` (BE-2).
- **`$ref` URIs are stored data.** Until WP-5g, every reader accepts `{"$ref": "/api2/query/<endpoint>/<id>"}` through `harmony.core.refs.parse_legacy_ref`.

## Known defects to fix with a failing test first

- `query_models.py:185`: `Thread(...).run()` serialises synchronously.
- `query_models.py:266`: `include_outliers` is always False.
- `line_graph.py:52-69` and `data_quality_report.py:346-350`: sub-queries run one after another.
- `map.py:192-193`: the frame is filtered once per date.
- `druid_context.py:112-114`: a new memoize wrapper is created on every access.

## Checks

```bash
uv run pytest tests/golden tests/authz -q
uv run mypy harmony/core
uv run lint-imports
python3 scripts/perf/baseline.py --compare
```

`lint-imports` arrives with WP-2f and the baseline script with WP-1a. Until then, record what you ran instead.
