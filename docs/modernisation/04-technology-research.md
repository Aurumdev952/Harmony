# 04. Technology research

Back to [overview](overview.md).

Research pass run on 2026-10-04. Package versions come from the npm and PyPI registries on that date. The `@heroui/react` 3.2.6 tarball and the Urbanist font tables were inspected directly. Everything else comes from the sources listed. Points that could not be confirmed are marked **unverified**. Re-check versions before each phase starts.

## Summary

| Area | Today in Harmony | Current release | Decision |
|---|---|---|---|
| UI kit | in-house `ui/`, Bootstrap 3 SCSS | HeroUI 3.2.6 (v3 stable since 2026-03-21) | HeroUI v3 |
| CSS | SCSS | Tailwind CSS v4 | Tailwind v4 (HeroUI v3 requires it) |
| React | 16.13 | 19 | React 19 (HeroUI v3 requires it) |
| Typeface | Lato | Urbanist variable 100–900; `@fontsource-variable/urbanist` 5.3.0 | Urbanist plus a figure face |
| Bundler | webpack 5.80 | Vite 8.3.2 (Rolldown), Vitest 5.0.3 | Vite 8 |
| Types | Flow 0.144 | TypeScript 7.0 (native, no programmatic API); TypeScript 6 | TypeScript 6, with 7 optional for fast checks |
| Web framework | Flask 1.0.1 | FastAPI 0.142.2, Pydantic 2.13.5, Starlette 1.7.0 | FastAPI |
| ORM | SQLAlchemy 1.3.24 | SQLAlchemy 2.1.3 (needs Python 3.11+) | 2.x, sync sessions |
| GraphQL | Hasura v2.11.3 | v2.45 LTS (EOL Dec 2027); DDN is a separate product | Retire it |
| Client data | Relay experimental, `$.ajax` | relay-runtime 21; TanStack Query 5.104; hey-api 0.99 | TanStack Query with hey-api |
| Warehouse | Druid 0.23.0 | Druid 38.0.0 (2026-10-01) | 37 or 38 on Java 21 |
| Python | 3.8 / 3.9 / PyPy 3.9 | 3.14 stable; 3.15 final due 2026-10-09 | 3.13 now, 3.14 later |
| Packaging | pip, four requirements files | uv 0.12.23 | uv |
| Pipeline engine | per-row Python on PyPy | Polars 1.44.2, pandas 3.0.6, PyPy 8.0 (last 3.11 line) | Polars, CPython |
| Orchestration | cron and Zeus | Dagster 1.13, Prefect 3.8, Airflow 3.3 | Dagster |
| Server | gunicorn 20 with gevent | uvicorn 0.54, Granian 2.8.4 | uvicorn |
| Jobs | Celery 5.4 | Celery 5.6.3 | keep Celery |

## HeroUI v3

- It is a rewrite on React Aria Components and Tailwind v4. The peer dependencies are `react >=19`, `tailwindcss >=4`, `react-aria-components ^1.21.1` and `@internationalized/date ^3.12.4`.
- **Exports confirmed in the 3.2.6 tarball:** table, autocomplete, combo-box, select, calendar, range-calendar, date-field, date-picker, date-range-picker, time-field, modal, alert-dialog, drawer, dropdown, menu, popover, tabs, toast, tooltip, pagination, breadcrumbs, accordion/disclosure, number-field, search-field, tag-group, toolbar, skeleton, empty-state and the colour pickers.
- **Missing:** a tree and a navbar. For trees, use React Aria's `Tree` through HeroUI's `rac` re-export and style it with our own tokens. The navbar is built from Tailwind and HeroUI primitives.
- **Table virtualises, but it is not a data grid.** It has no pinning, grouping or range selection. Use TanStack Table for heavy grids.
- **Theming:** OKLCH CSS variables, `--font-sans` and `--font-mono`, dark mode through `.dark` or `data-theme`, and RTL-aware CSS.
- **Ethiopian calendar:** `@internationalized/date` ships `EthiopicCalendar` and `EthiopicAmeteAlemCalendar`. Import those classes directly instead of calling `createCalendar`, which pulls in every calendar.
- **Size:** the prebuilt CSS is 39 KB gzipped. Compile from source to tree-shake it.
- **Constraints:**
  - Tailwind v4 targets Chrome 111, Safari 16.4 and Firefox 128.
  - Tailwind v4 is not meant to be mixed with Sass in the same files.
  - HeroUI v2 and v3 cannot coexist.
- **Unverified:** the docs site rejected automated fetches, so RTL quality and Table column resizing and sticky headers are unconfirmed.

Sources: [InfoQ on the v3 rewrite](https://www.infoq.com/news/2026/07/heroui-v3-rewrite/), [React Aria calendars](https://react-aria.adobe.com/internationalized/date/Calendar), [Tailwind compatibility](https://tailwindcss.com/docs/compatibility).

## Urbanist

- Google Fonts, OFL licence. One `wght` axis from 100 to 900, with italics.
- **Glyph coverage:** Latin and Latin Extended (491 code points). No Ethiopic, Cyrillic or Vietnamese.
- **No tabular figures.** The font's substitution table holds only `aalt, ccmp, frac, ordn, sinf, subs, sups`, and the digits are proportional ("1" is 530 units wide, "0" is 1191). `font-variant-numeric: tabular-nums` has no effect.
- **Fallback for Amharic:** Noto Sans Ethiopic, which is variable in weight and width. Its Latin subset has fixed-width digits (every digit is 572 units, checked in `@fontsource-variable/noto-sans-ethiopic`). So it has tabular figures by default, even without a `tnum` feature. The Ethiopic subset has no ASCII digits, so it falls back for those.

Source: [Noto Sans Ethiopic](https://fonts.google.com/noto/specimen/Noto+Sans+Ethiopic).

## Vite 8

- Rolldown is the only bundler. Oxc does the transforms and Lightning CSS minifies. It needs Node 20.19+ or 22.12+.
- `build.rollupOptions` is now `build.rolldownOptions`. Old configs are converted automatically.
- **Backend integration:**
  - Put all entries in `rolldownOptions.input` and set `build.manifest: true`.
  - The server reads `.vite/manifest.json` and emits the script, CSS and `modulepreload` tags for each entry.
  - In development, templates inject `@vite/client` and the React refresh preamble.
- **Flow, Relay and decorators need Babel.** `@vitejs/plugin-react` 6 removed its `babel` option. Run Babel through `@rolldown/plugin-babel` with:
  - the Hermes or Flow strip plugin,
  - `babel-plugin-relay`,
  - `@babel/plugin-proposal-decorators` in legacy mode.

  Avoid `vite-plugin-relay` (last published 2024-01). Whether Oxc can lower legacy decorators on its own is **unverified**.

Sources: [Vite 8 announcement](https://vite.dev/blog/announcing-vite8), [backend integration guide](https://vite.dev/guide/backend-integration), [plugin-react README](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react/README.md).

## FastAPI

- 0.142 needs Python 3.10+ and added native OpenTelemetry in 0.142.0.
- `fastapi-users` is in maintenance mode. Use Authlib 1.8 for OIDC and keep our own session and permission layer.
- Starlette's own `WSGIMiddleware` has been deprecated since 0.19. If a mount is ever needed, use `a2wsgi` 1.10.10. This plan routes at nginx instead.
- Code generation: `@hey-api/openapi-ts` (pre-1.0, with a TanStack Query plugin), orval 8 (adds MSW mocks), or `openapi-typescript` 7 (types only).
- Granian benchmarks about 2× faster than uvicorn on synthetic loads and within 5–10% on database-bound ones.

Sources: [PyPI fastapi](https://pypi.org/project/fastapi/), [release notes](https://fastapi.tiangolo.com/release-notes/), [FastAPI WSGI docs](https://fastapi.tiangolo.com/advanced/wsgi/), [Starlette deprecation PR](https://github.com/Kludex/starlette/pull/1504), [fastapi-users](https://github.com/fastapi-users/fastapi-users), [Granian vs uvicorn](https://blog.hashhackers.com/blog/granian-uvicorn-asgi/), [hey-api TanStack plugin](https://heyapi.dev/docs/openapi/typescript/plugins/tanstack-query).

## Apache Druid

- 38.0.0 was released 2026-10-01. It supports Java 21 and 25, drops Java 17, and removes the ZooKeeper task runner and ZooKeeper segment discovery.
- **Null handling:** SQL-compatible handling became the default in 28. In 32, `useDefaultValueForNull=true` and the related legacy settings were removed, and services refuse to start if those settings are present. Nulls are no longer `""` or `0`. **Every Harmony query that relies on the old behaviour has to be audited.**
- **Ingestion:** SQL-based (MSQ) `INSERT` and `REPLACE` are fully supported. Native `index_parallel` is not deprecated. Hadoop ingestion was deprecated in 32.
- **Repository risks:**
  - `-XX:+PrintGCTimeStamps` and `-XX:+PrintGCDetails` must become `-Xlog:gc*`. That the JVM refuses to start with them is **unverified** for this exact JDK.
  - `druid_javascript_enabled=true` must go.
  - `pydruid` was last released 2024-05 and is used in 53 files.
- **ClickHouse:** a single node is simpler to run than Druid's process set, and DHIS2 now supports ClickHouse as its analytics store. Switching means rewriting the query layer. It is worth doing only if Druid operations turn out to be the main operator burden, and phase 8f measures that.
- **DuckDB** is the wrong primary store because it allows one writer process. It is a good fit inside the pipeline.

Sources: [Druid](https://druid.apache.org/), [38.0.0 release](https://github.com/apache/druid/releases/tag/druid-38.0.0), [release notes](https://druid.apache.org/docs/latest/release-info/release-notes/), [32.0.0 release](https://github.com/apache/druid/releases/tag/druid-32.0.0), [ingestion](https://druid.apache.org/docs/latest/ingestion/), [concurrent append and replace](https://druid.apache.org/docs/latest/ingestion/concurrent-append-replace), [pydruid](https://github.com/druid-io/pydruid), [DuckDB concurrency](https://duckdb.org/docs/current/connect/concurrency), [ClickHouse vs Druid](https://oneuptime.com/blog/post/2026-01-21-clickhouse-vs-druid/view), [DHIS2 analytics database PR](https://github.com/dhis2/dhis2-core/pull/24440).

## Pipeline, orchestration and Python

- **PyPy:** 8.0 is the last release on the 3.11 line, and its 3.12 support is beta. Harmony is on PyPy 3.9, which is out of support.
- **Polars** beats pandas 3 to 10 times on columnar work. That only holds if transforms are written as expressions. Per-row `map_elements` loses most of the gain.
- **Dagster's asset model** matches how Zeus steps fit together. Prefect is lighter to run, and Airflow 3 is the heaviest. The comparison sources are vendor-adjacent, so treat them as weak evidence.
- **Hasura v2.11** has been retired since 2024-09-01.
- **Python:**
  - 3.15's final release slipped to 2026-10-09.
  - Dagster, Prefect and clickhouse-connect cap below 3.15.
  - Free-threading does not help an I/O-bound web tier.
- **DHIS2 pull patterns** (incremental `lastUpdated` pulls) were not researched. Research them in phase 8.

Sources: [PyPy 8.0](https://pypy.org/posts/2026/09/pypy-v800-release.html), [Polars vs pandas](https://www.danilchenko.dev/posts/polars-vs-pandas/), [orchestrator comparison](https://www.zenml.io/blog/orchestration-showdown-dagster-vs-prefect-vs-airflow), [Hasura versioning](https://hasura.io/docs/2.0/policies/versioning/), [Hasura v2 support policy](https://hasura.io/legal/support-policy-hasura-v2), [Python 3.15.0rc3](https://www.python.org/downloads/release/python-3150rc3/).
