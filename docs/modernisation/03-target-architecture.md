# 03. Target architecture

Back to [overview](overview.md).

This is where the system ends up once every phase has landed. The phases describe how to get there in steps that can each be checked. Versions are pinned to what was current on 2026-10-04 (see [04-technology-research.md](04-technology-research.md)).

## Topology

```
                         nginx (TLS, static assets with immutable caching)
                           │
        ┌──────────────────┴───────────────────┐
        ▼                                      ▼
  FastAPI (uvicorn, Python 3.13)          static SPA shell (Vite build)
   ├─ /api/v3/*  REST, OpenAPI 3.1          index.html + hashed chunks + service worker
   ├─ /auth/*    login, reset, invite
   ├─ /render/*  self-hosted Playwright screenshots and PDFs
   └─ OpenTelemetry traces and metrics
        │                 │                  │
        ▼                 ▼                  ▼
   harmony.core       Postgres 18         Redis 7
   (framework-free)   metadata, users,    result cache, sessions,
   query engine,      catalog, jobs       Celery broker
   permissions,
   datasource registry
        │
        ▼
   Druid 37/38 on Java 21 (SQL API, native expressions, no JavaScript)
        ▲
        │ Parquet via SQL ingestion (REPLACE ... OVERWRITE WHERE month)
   Pipeline: Dagster assets on Python 3.13 + Polars, MinIO/S3 for intermediates
```

Two services leave the stack: Hasura and the urlbox SaaS. PyPy and the second requirements tree leave the pipeline. Nothing new is added that a small team has to run, apart from the Dagster daemon, which replaces host cron.

## Backend

### Package layout

```
harmony/
  core/            framework-free; importable by the API, workers, pipeline and scripts
    settings.py    pydantic-settings, replaces config/settings.py and the ZEN_ENV import hook
    deployment.py  loads config/<code>/ through importlib.util.find_spec; no import-time I/O
    db.py          SQLAlchemy 2 engine and session factory; no current_app
    query/         QueryRequest (Pydantic v2), builder, executor, post-processing
    druid/         thin httpx client for native JSON and SQL, timeouts, retries
    authz/         roles, ACLs, query policies as pure functions of a Principal
    cache.py       result cache keyed on (datasource version, request hash, policy hash)
  api/             FastAPI app: routers, dependencies, OpenAPI
  worker/          Celery app that imports harmony.core, not the web app
  pipeline/        Dagster definitions wrapping the existing step scripts
```

`AppContext` is a plain dataclass that holds settings, the deployment config, the engine, the Druid client, the cache and the datasource registry. FastAPI builds one at startup and hands it to handlers through `Depends`. Celery tasks, scripts and the pipeline build the same object. That removes the dependency of 21 non-web files on Flask's app context (`web/server/data/data_access.py:4-17`).

### API design

- **REST with OpenAPI 3.1, under `/api/v3/`.** Each domain is one router (`query`, `dashboards`, `alerts`, `catalog`, `uploads`, `data_quality`, `digest`, `admin`, `users`, `config`).
- **IDs instead of URIs.** Responses carry `id`. The `$ref`/`$uri` convention ends in phase 5. Stored specs that still contain `$ref` strings go through one tolerant reader, `harmony.core.refs.parse_legacy_ref`, until the phase 5g data migration rewrites them. Then the reader is deleted.
- **List endpoints share one filter vocabulary:** `?filter[field]=value`, `?sort=-created`, `?page[size]&page[cursor]`, with total counts in the body. The Potion `where={...}` JSON (30 call sites) moves to this pattern as each domain migrates.
- **The catalog replaces Hasura.** Data Catalog, Field Setup and Data Upload read and write through `/api/v3/catalog/*`. The field catalog the frontend loads on every page becomes a versioned, ETagged document (`GET /api/v3/catalog/fields`, `ETag: <catalog version>`). The browser keeps it in IndexedDB.
- **A typed query contract.** `QueryRequest` becomes a Pydantic model whose JSON Schema is published in OpenAPI. That schema is the semantic layer the LLM roadmap item needs: a model can be told "produce a `QueryRequest`" and the server validates the result before it touches Druid.

### Authentication and authorisation

- **Session.** Keep the current design, which is a signed JWT in an httpOnly `accessKey` cookie (`web/server/util/authentication.py:25-57`). During migration both Flask and FastAPI verify it with the same secret. At the end the cookie becomes `SameSite=Lax`, the lifetime drops from 365 days to a configurable value, a refresh token is added, and double-submit CSRF protects unsafe methods.
- **Separate keys.** `SECRET_KEY` and `JWT_SECRET_KEY` become different values. The app refuses to start with the default value.
- **Reset and invite tokens.** Flask-User's tokens are replaced by single-use rows in Postgres (hashed token, expiry, purpose). Tokens already outstanding at cutover are honoured by a verifier that is deleted after the longest token lifetime has passed.
- **Authorisation.** `harmony.core.authz` turns the Flask-Principal `needs` model into a `Principal` value (user id, roles, ACL grants, query-policy filters). Permission checks become pure functions, `can(principal, action, resource) -> bool`, so they can be tested without a request. The Potion signal hooks (`web/server/security/signal_handlers.py:341-381`) become explicit calls inside each router's service function.
- **SSO.** Authlib is used for OIDC. Many ministries run Keycloak or Azure AD, and SSO removes password-reset email from the critical path.

### Query execution

```
QueryRequest (validated) ─▶ policy filter applied ─▶ cache lookup ─hit─▶ response
                                                        │ miss
                                                        ▼
                         build Druid query(ies) ─▶ httpx.AsyncClient (timeout, priority)
                                                        │  run sub-queries concurrently
                                                        ▼
                         Arrow/Polars frame from array rows ─▶ visualization shaper
                                                        │  (CPU work in a worker thread)
                                                        ▼
                         orjson bytes ─▶ cache store ─▶ response (streamed for tables)
```

- **Cache key:** `(datasource_version, sha256(canonical QueryRequest JSON), sha256(policy filter))`. A new datasource changes the version, so stale entries can never be served, and no explicit invalidation is needed. Entries expire after 24 hours by default.
- **Concurrency:** handlers are `async`. Druid I/O runs on the event loop. Post-processing runs through `anyio.to_thread.run_sync`, and Polars releases the GIL inside its kernels. Druid queries carry `context.timeout` and a priority, so dashboard tiles are not starved by exports.
- **Wire format:** columnar JSON (`{columns: [...], rows: [[...]]}`) serialised by orjson. Arrow IPC is an option for the table and export endpoints once the frontend can decode it. It is not planned yet.

### Background work

Celery stays on Redis. Its job list grows from email and SMS to:
- dashboard export rendering (self-hosted Playwright),
- alert evaluation, moved out of the pipeline,
- scheduled dashboard emails, which gives the existing `SchedulerEntry` table a consumer through Celery beat.

Procrastinate (Postgres-backed) would let us drop Redis. That only pays off if the result cache moves too, so it is noted and not planned.

### Observability

- Structured JSON logs to stdout, collected by Docker or the host.
- OpenTelemetry traces through FastAPI's built-in support, covering FastAPI → Druid → Postgres. Exported over OTLP to whatever the deployment runs. Grafana Alloy plus Tempo is the documented default.
- A Prometheus `/metrics` endpoint: request latency per route, Druid latency, cache hit rate, queue depth.
- A health endpoint that separates liveness from readiness. Page renders stop calling Druid.

## Frontend

### Platform

| Concern | Choice |
|---|---|
| Build | Vite 8 (Rolldown) |
| Language | TypeScript 6 (strict), converted from Flow with `flow-to-ts`. TypeScript 7 (`tsgo`) is optional for fast checks, because typescript-eslint needs the version 6 API. |
| UI runtime | React 19 |
| Server state | TanStack Query 5, with hooks generated from OpenAPI by `@hey-api/openapi-ts` |
| Routing | TanStack Router, file-based, inside one SPA shell (end state) |
| Domain models | Zen models stay where they model query and dashboard specs; generated OpenAPI types everywhere else |
| Styling | Tailwind CSS v4 and HeroUI v3 tokens; SCSS retired |
| Charts | visx for the existing @vx charts; d3 v7 modules for sunburst and tree; MapLibre through react-map-gl 8 |
| Tests | Vitest 5, Testing Library, Playwright for end-to-end and visual checks |
| Offline | `vite-plugin-pwa` with Workbox: precache the shell, cache the catalog in IndexedDB, stale-while-revalidate for recently viewed dashboard results |

Relay and its compiler leave with Hasura. jQuery, bluebird, moment, toastr, Bootstrap JS and SCSS, react-modal, react-day-picker, react-spring 8, the d3 v3 global and Plotly 1.22 all leave too. Each removal is listed in the phase that does it.

### From many pages to one app

The 19 Jinja templates become one `index.html`. The server data that pages read from `window.__JSON_FROM_BACKEND` (about 35 keys and 124 read sites) becomes `GET /api/v3/session/bootstrap`, which is typed, cached and fetched once. Deep links such as `/dashboard/<slug>`, `/advanced-query` and `/data-catalog/...` become router routes, so existing bookmarks keep working. Embedded and screenshot modes become route-level layouts (`/embed/...`, `/render/...`) instead of query-string checks.

## Design system

### Tokens

`web/client/design/tokens.css` is the single source of truth. It holds Tailwind v4 `@theme` variables plus the HeroUI v3 theme variables. Two hand-synchronised copies exist today (`web/public/scss/_zen_variables.scss` and `web/client/components/ui/Colors.js`). Both are replaced: `Colors.js` becomes a generated file that reads the same tokens, and that covers the chart code that needs colours as JS values.

The colour mapping starts from the current palette, so the product stays recognisable, and the redesign adjusts it from there:

| Current SCSS | HeroUI role |
|---|---|
| `$blue-primary #3597e4` and its hover and active shades | `accent` / primary scale |
| `$success`, `$error`, `$warning`, `$info` families | `success`, `danger`, `warning`, and an `info` addition |
| grays and slates | `default` neutral scale and `background`/`surface` |
| `$site-background #fafafb` | `background` |

Dark mode comes free from HeroUI's `.dark` theme. Ship it once every page has moved off SCSS.

### Typography

Urbanist is a geometric sans with a variable weight axis from 100 to 900. It has two gaps that matter for this product:
1. **Script coverage is Latin and Latin Extended only.** French and Portuguese work. Amharic needs a fallback.
2. **It has no `tnum` feature, and its digits are proportional** (the research pass inspected the font tables). Columns of numbers will not line up, and chart axes will jitter as values change.

The stack:

```css
--font-sans:    "Urbanist Variable", "Noto Sans Ethiopic", system-ui, sans-serif;
--font-numeric: "Inter Variable", "Noto Sans Ethiopic", system-ui, sans-serif;  /* tnum, lnum */
```

`--font-sans` covers everything a person reads as text: navigation, headings, labels, buttons and prose. `--font-numeric`, with `font-variant-numeric: tabular-nums lining-nums`, covers table cells, KPI tiles, chart axes and tooltips, date pickers and pagination.

Inter is the default numeric face because its tabular figures are well tested. Phase 7a runs a prototype comparing three options against real dashboard screenshots before the choice is fixed:
- Inter for figures,
- IBM Plex Sans for figures,
- Noto Sans Ethiopic for figures. Its digits are already fixed-width, and Amharic deployments load it anyway, so it adds no download.

Urbanist everywhere, with figures right-aligned in fixed-width cells, is the control.

Fonts are self-hosted through Fontsource packages. That is required for offline use and for the export renderer, which needs fonts inlined (`web/client/components/common/SharingUtil/canvas_util.js`).

### Components

The `ui/` library shrinks to the components HeroUI does not cover. The full mapping is in [05-ui-surface-inventory.md](05-ui-surface-inventory.md). In short:
- **Replace with HeroUI (about 40 modules):** Button, Input, Select/Autocomplete, Checkbox, Radio, Switch, Tabs, Modal, Drawer, Popover, Tooltip, Toast, Table, Pagination, Breadcrumbs, Chip, Card, Accordion, Slider, Progress, Spinner, Alert, Link.
- **Replace with Tailwind utilities:** `Group`, `Spacing`, `Heading`, `Caret` (313 importers combined).
- **Keep and restyle on tokens:** `HierarchicalSelector` (built on React Aria `Tree` where it fits), the `DatePicker` shell (Ethiopian calendar through `@internationalized/date`'s `EthiopicCalendar`), `ColorBlock`, `DraggableItemList` (React Aria drag and drop), `UploadInput`, `TextHighlighter`, and the visualization primitives.
- **Heavy grids:** TanStack Table renders inside HeroUI table markup, with virtualisation from TanStack Virtual. The Table visualization keeps its `react-window` approach until then.

## Data platform

- **Druid 37 or 38 on Java 21, with ZooKeeper removed** (38 drops the ZooKeeper task runner and segment discovery). SQL-compatible null handling is mandatory and gets audited in phase 8a. JavaScript is disabled. Week extraction and `js_formulas` move to native expressions.
- **Ingestion:** SQL-based (MSQ) `REPLACE INTO <datasource> OVERWRITE WHERE __time >= <month start> AND __time < <next month>`, reading Parquet. Each run replaces only the months whose inputs changed, so the datasource name stays stable and the "newest datasource" lookup goes away.
- **Partitioning:** range partitioning on `field` (then `source`) inside each month, sized by `targetRowsPerSegment`.
- **Pipeline:** Python 3.13 and Polars. `process_csv` and `fill_dimension_data` become Polars lazy frames that write Parquet once. Row-level Python hooks keep a `map_elements` escape hatch with a deprecation warning.
- **Orchestration:** Dagster assets, one per source plus one per indexed month. Each Zeus step becomes an op that wraps the existing script unchanged, then gets rewritten as it is touched. Retries, run history, partial reruns and alerts on failure come with Dagster. The `|| true` that hides failures goes away.
- **Decision gate:** a time-boxed ClickHouse prototype on one real deployment's data, measured on query latency, memory and operator effort. A switch happens only if it wins on operator cost without losing on latency.

## Decisions

| Decision | Choice | Main reason | Rejected |
|---|---|---|---|
| Flask to FastAPI route | nginx path routing, shared JWT | Keeps gevent semantics for routes not yet moved; no session bridge needed | a2wsgi mount, big-bang rewrite |
| GraphQL | Retire Hasura and Relay | Hasura v2.11 has been out of support since 2024-09; one API style; removes a service | Upgrade to Hasura 2.45 LTS (kept only as an interim security fix) |
| Generated client | hey-api with the TanStack Query plugin | Typed hooks straight from OpenAPI | orval (fine, adds MSW we do not need yet), hand-written services |
| ORM | SQLAlchemy 2, sync sessions | 200 files use it; async adds risk with no gain for metadata queries | async SQLAlchemy |
| Server | uvicorn, one worker per core | Within 5 to 10% of Granian on I/O-bound work, easier to debug | Granian |
| Python | 3.13 | SQLAlchemy 2.1 and pandas 3 need 3.11 or newer; several dependencies cap below 3.15 | 3.14 (move later), PyPy |
| UI kit | HeroUI v3 | Requested. Built on React Aria, so accessibility and Ethiopic calendar support are covered | HeroUI v2 (cannot coexist with v3, built on the old Tailwind) |
| Typeface | Urbanist plus a figure face with tabular numerals | Requested. The figure face fixes the missing `tnum` | Urbanist alone |
| Frontend shape | One SPA plus a PWA | Offline and mobile roadmap | Keep the multi-page app |
| Exports | Self-hosted Playwright in a sandboxed renderer sidecar, dispatched from the Celery worker after WP-5f (decision 0009) | Cost and data sovereignty | urlbox.io |
