# 02. Architecture deep dive: performance, efficiency and fit to goals

Back to [overview](overview.md).

This is a static read of the code. Nothing was profiled at runtime, and claims that need a runtime check are marked **unverified**. Phase 1 starts by capturing a baseline so every claim here can be measured before and after.

## What the system is optimising for

The README sets out five commitments:
1. **Sub-second analytics** over millions of rows.
2. **Integration of messy, multi-source data** into one queryable model.
3. **Dashboards, alerts and data quality** for programme staff.
4. **Low cost of ownership.** Small teams, modest hardware, on premises or in the cloud.
5. **Roadmap:** pipeline performance, mobile and offline dashboards, LLM-assisted querying, self-service integration tooling, monitoring.

The rest of this document judges each part of the architecture against those five.

## The data model

The Druid table is tall and narrow. A row holds the dimensions, the date, the source and the `field`, plus one `val` metric, rolled up at ingest into `count`, `sum`, `min` and `max` (`config/druid_base.py`, `db/druid/indexing/common.py:33-38`). Zero values for the same key collapse into one row with a multi-valued `field` (`data/pipeline/datatypes/base_row.py:146-154`).

This is the right shape for the product.
- **New indicators never change the schema.** That is what self-service integration needs.
- **The bitmap index on `field` is the main filter.** Selecting a handful of indicators is a cheap intersection.
- **Each indicator becomes a filtered aggregator.** The OR of all aggregator filters is pushed down as the query filter (`db/druid/query_builder.py:200-218`), so Druid scans only the rows for the requested fields.

There are two costs.
- **Every formula is a post-aggregation.** Formulas combine separately filtered sums.
- **Partitioning does not scale.** It uses `hashed` with `numShards: 1` and `segmentGranularity: MONTH` (`db/druid/indexing/common.py:32`), so each month is one segment regardless of size. This will hurt once a month passes about five million rows (**unverified** for current deployments). Range partitioning on `field` would prune better.

**Verdict.** Keep the model. Change the partitioning in phase 8.

## The query hot path

```
Browser QueryEngine ─POST─▶ Potion QueryResource ─▶ related.to_model(QueryRequest)
   (per tile, ≤6 in flight)        (query_models.py)        (Python object graph)
                                                                   │
        JSON ◀─ pandas post-process ◀─ dict-per-row parse ◀─ Druid groupBy ◀─ GroupByQueryBuilder
```

### What works

- One Druid query per bar, table, hierarchy or map visualization. Subtotals come back in the same query through `subtotalsSpec` (`query_builder.py:303`).
- The query-policy filter is computed in memory from `g.identity` with no extra round trip (`web/server/routes/views/query_policy.py:322-328`).
- The Druid client streams gzip and parses with `ijson` (`db/druid/query_client.py:135`).
- Dashboard tiles load lazily with `react-lazyload`, and the client limits in-flight queries to 6 (`web/client/components/visualizations/common/QueryInterface.js:23`).

### Where time and money go

| # | Finding | Evidence | Effect |
|---|---|---|---|
| 1 | No server-side result cache for queries. The only cache is per browser tab, and its key is unstable by its own comment. | `QueryInterface.js:17,117-120`. `CachedRoute` is used only for dimension values (`web/server/api/api_models.py:81`). | Every user's dashboard load hits Druid for the same tiles. |
| 2 | Druid rows become one dict per row. The timestamp is formatted per row and fields are walked per row. The code's own TODO says arrays would be "a lot faster". | `db/druid/query_builder.py:376-386` | CPU per request grows with rows × fields, in Python. |
| 3 | The DataFrame is built from lists of dicts in 100k chunks with repeated `pd.concat`. | `query_builder.py:652-687` | Copying grows quadratically on large results. |
| 4 | The map visualization filters the whole frame once per date. | `web/server/query/visualizations/map.py:192-193` | Cost is O(dates × rows). |
| 5 | Line graph, bump chart and heat tiles run two Druid queries in sequence. Data quality runs three. | `line_graph.py:52-69`, `data_quality_report.py:346-350` | Latency doubles or triples. |
| 6 | The table "stream" calls `Thread(...).run()`, which serialises the whole payload synchronously before responding. | `web/server/api/query/query_models.py:185` | No streaming and full memory cost, despite the comment. |
| 7 | `session.post` to Druid has no timeout, and queries carry no `context.timeout`. | `db/druid/query_client.py:75` | One bad query can hold a worker for the 600-second gunicorn timeout. |
| 8 | Gunicorn runs gevent workers with `reload: True` set unconditionally, including in production. | `web/gunicorn_server.py:7-9,159` | Production workers watch files. CPU-bound pandas work blocks every greenlet in its worker. |
| 9 | `current_db_datasource` builds a new memoize wrapper on each access, so each read costs a Redis GET. It is read several times per request. | `web/server/data/druid_context.py:112-114` | Avoidable round trips on every request. |
| 10 | Every page render calls Druid status. | `web/server/util/template_renderer.py:141` | Page loads are coupled to Druid availability. |
| 11 | Each gunicorn worker repeats the row-count, data-status and dimension-metadata Druid queries on first use (`lru_cache(1)` per process). | `druid_context.py:54-75,161-175` | Cold-start load grows with the number of CPU cores. |
| 12 | Druid has JavaScript enabled cluster-wide for `js_formulas` and week extraction. | `druid_setup/*/environment/common.env` | Slower than native expressions, a security surface, and a blocker for the Java 17+ upgrade. |

## Dashboards and pages

- `grid_dashboard.html:8` loads `plotly-1.22.0.js` (about 1.9 MB) as a blocking script. The bubble chart, the only component that uses it, already lazy-loads it through `withScriptLoader`.
- `query_app_vendor_scripts.html` is included 13 times. It blocks on d3 v3, an acorn interpreter, bootstrap-select, bootstrap-datepicker and rbush. Nothing in `web/client` calls `selectpicker` or `.datepicker`.
- `layout.html` loads jQuery, Bootstrap 5 JS and toastr on every page.
- Bundles are named `[name].bundle.js` with no content hash (`web/webpack.prod.config.js:146`). nginx serves them with ETag revalidation only, so every page load revalidates every bundle.
- One shared `vendor` chunk holds all `node_modules` for all 19 entries. The login page downloads Mapbox's dependency graph.
- The indicator catalog loads through Hasura on every page. It fetches every field's serialised calculation, unpaginated (`patchFieldService.js`), through a Flask proxy that buffers the whole response (`web/server/routes/api.py:174`).
- Dashboard PDF and image export goes to urlbox.io (`web/server/routes/views/page_renderer.py:13,97-125`). Each export is a fixed 10-second delay plus a 120-second wait, and it is a paid service that sends dashboard contents to a third party. That is a data-sovereignty problem for a ministry.

## The pipeline

```
CSV ─DictReader─▶ row handlers ─▶ BaseRow ─to_json─▶ .json.lz4
      ─decode─▶ location dict join ─encode─▶ 3M-row .json.gz shards ─▶ Druid parses JSON again
```

- Data is serialised to JSON three times and parsed three times. Every transform is a per-row Python loop (`data/pipeline/scripts/process_csv.py:255,315,365,388`). The file itself says "lots of room for optimization" (line 41).
- PyPy is used to make those loops bearable. In exchange, numpy is pinned to 1.15.4 and shapely to 1.8, and two dependency sets are kept in step. PyPy 8.0 is the last release on the 3.11 line.
- Each run rebuilds a new datasource for all time (`db/druid/indexing/task_runner_util.py:152`). The only shortcut skips the run when the file set is byte-identical (`run_native_indexing.py:163-176`). Segments are already monthly, so replacing only the months that changed is a small step from here.
- The index step finishes with a fixed `sleep 120` (`10_wait_for_complete.abort_fail:23`). `process_all:20` hides step failures with `|| true`.
- Location matching is exact lookup against `mapped_locations.csv`. `fuzzywuzzy`, `jellyfish` and `editdistance` are installed, but nothing in the repo imports them.

Every loop above is one columnar expression in Polars or DuckDB. Druid reads Parquet natively, so the intermediate JSON passes go away entirely.

## Gap analysis against the goals

| Goal | Today | Evidence | What changes it |
|---|---|---|---|
| Sub-second analytics | Partly met | Druid and filter pushdown are sound. Python parsing, no shared cache and sequential multi-query visualizations add latency on top. | Phase 1 (cache, columnar parse, timeouts). Phase 5 (async Druid calls). |
| Integrate messy data | Met, slowly | The tall model absorbs new sources. Throughput is capped by per-row Python. | Phase 8 (Polars, Parquet, incremental indexing) |
| Dashboards, alerts, data quality | Met, with bugs | Outliers are never computed (`query_models.py:266`). The alerts page renders 404 (`web/server/routes/index.py:69-73`). | Phase 0 and phase 1 bug fixes |
| Low cost of ownership | Mixed | Druid with ZooKeeper, Hasura, Redis, MinIO, PyPy and a paid render service is a lot to run. | Retiring Hasura (phase 5), PyPy (phase 8) and urlbox (phase 1). The ClickHouse gate (phase 8f). |
| Pipeline performance | Blocked by design | Full rebuild per run, sleep-based waiting, no SQL ingestion on 0.23. | Phase 8 |
| Mobile and offline | Blocked | Server-rendered pages, about 2.5 MB of blocking vendor JS, no service worker, in-memory cache only. | Phases 6 and 7 (Vite, single-page shell, PWA) |
| LLM-assisted querying | Close | `QueryRequest` is already a typed JSON query model, which is most of a semantic layer. It has no published schema and no guard against runaway queries. | Phase 5b (Pydantic `QueryRequest` with JSON Schema). Phase 1 (timeouts). |
| Self-service integration | Partly met | Fields are data in Postgres. Dimensions and hierarchies are Python in `config/<code>/datatypes.py`. | Phase 4 (typed settings). A later project to move dimension config into the database. |
| Monitoring | Missing | No metrics or traces on the hot path. Logs go to 512 KB rotating files. | Phase 2 (structured logs). Phase 5 (FastAPI's built-in OpenTelemetry). |

## Bugs found during the dive

Each of these gets a failing test before its fix, per `pstack:tdd`.

| Bug | Evidence | Phase |
|---|---|---|
| `include_outliers = exclude_outliers is None and not True` is always False, so outliers are never computed | `web/server/api/query/query_models.py:266` | 1 |
| Table serialisation runs `Thread.run()` instead of `start()` | `query_models.py:185` | 1 |
| The pipeline Compose file sets `POSTGRES_DB_URI:` (with a trailing colon), so Alembic never receives the URI | `docker-compose.pipeline.yaml:17` | 0 |
| `url_for('index.unauthorized')` points at the wrong blueprint | `web/server/routes/dashboard.py:44` | 0 |
| `is_session_persisted` checks a cookie the JWT login never sets | `web/server/util/util.py:622` | 0 |
| `grid_dashboard.html` references `asyncMapChunk.bundle.js`, which webpack never builds (**unverified** 404 at runtime) | `web/server/templates/grid_dashboard.html:15` | 0 |
| The Jenkinsfile calls Makefile targets that do not exist | `ci/docker/Jenkinsfile:16-44` | 0 |
| `run_raw_query` skips the query policy | `web/server/routes/views/query_policy.py` | 0 (security) |

## The ten highest-value improvements

Ranked by impact divided by effort. Each one appears in a phase.

| Rank | Improvement | Impact | Effort | Phase |
|---|---|---|---|---|
| 1 | Shared Redis result cache keyed on datasource version, canonical request and policy hash | High | Low | 1 |
| 2 | Drop the eager Plotly tag and dead vendor scripts, defer the rest, hash bundle filenames | High on slow links | Low | 1 |
| 3 | Build DataFrames from Druid's array rows and vectorise post-processing | High on large results | Medium | 1 |
| 4 | Timeouts on Druid calls, remove `reload: True`, request-scoped datasource lookup | Medium (stability) | Low | 1 |
| 5 | Run totals and data-quality sub-queries concurrently, or merge them | Medium | Low | 1 |
| 6 | Real streaming for table results, with server-side pagination | Medium | Low | 1 |
| 7 | Self-hosted headless renderer instead of urlbox | Medium, plus sovereignty | Medium | 1 |
| 8 | Druid 37/38 on Java 21: SQL ingestion, native expressions only | High for the pipeline | High | 8 |
| 9 | Incremental, month-level replacement instead of full rebuilds | High | Medium | 8 |
| 10 | Polars or DuckDB pipeline writing Parquet; retire PyPy | High | High | 8 |
