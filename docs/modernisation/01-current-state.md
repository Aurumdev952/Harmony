# 01. Current state assessment

Back to [overview](overview.md).

This is a snapshot of the repository as of 2026-10-04 (commit `5671b02`). Every claim below points at a file so it can be re-checked as the code moves.

## What Harmony is

Harmony is an AGPL analytics platform built by Zenysis for ministries of health. It does two jobs.

1. **Data integration.** An ETL pipeline pulls data from DHIS2, OpenLMIS, CSV and Excel sources, harmonises dimensions such as locations, and loads the result into Apache Druid.
2. **Analytics.** A web application for ad-hoc queries (AQT), dashboards, alerts, the Data Quality Lab, the Data Catalog, Field Setup and administration.

Each country or programme is a *deployment*. A deployment owns `config/<code>/` (Python modules) and `pipeline/<code>/` (step scripts), and the `ZEN_ENV` environment variable selects it.

| Metric | Value |
|---|---|
| JS/JSX files | about 2,100 (1,802 of them carry `@flow`; there is no TypeScript) |
| Python files | about 840 |
| SCSS files | 243 |
| Alembic revisions | 143 (`web/server/migrations/versions`) |
| Automated tests | none (no `test_*.py`, no `*.test.js`) |
| Git history | 58 commits since the initial import on 2023-09-21 |

## Topology

```
 Sources (DHIS2, LMIS, CSV, APIs)
          │
          ▼
 PIPELINE  Python 3.9 + PyPy, Zeus step runner, host cron
   generate ─▶ process (process_csv, location matching) ─▶ index ─▶ validate
          │ mc CLI / boto3                       │ native index_parallel
          ▼                                      ▼
     MinIO / S3                         Druid 0.23 (+ZooKeeper, memcached)
                                        new datasource per run, keep 2
                                                 ▲
 WEB  Docker Compose                             │
   nginx-proxy + acme-companion                  │
     └─▶ Flask 1.0 on gunicorn/gevent ───────────┘ pydruid query builder
          ├─ /api2  Flask-Potion REST (forked; 51 files)
          ├─ /api/graphql ─▶ Hasura v2.11 ─▶ Postgres 15
          ├─ Jinja pages, one React bundle per page
          └─ Flask-User, Flask-Login, Flask-Principal, JWT
   Celery worker on Redis: email and SMS only
```

## Backend

- **App factory.** `create_app()` lives at `web/server/app.py:303`. Boot is eager. It seeds config, checks the Alembic head, syncs Druid metadata, builds the Druid context and the authorised query client (`app.py:202-224`).
- **Config is Python code.** A `sys.meta_path` importer in `config/__init__.py:23-83` maps `config.general` to `config/<ZEN_ENV>/general.py`. It uses `find_module`/`load_module`, which Python 3.12 removed. `config/<dep>/database.py:8` calls Druid at import time.
- **Query path.** A Potion `QueryResource` (`web/server/api/query/query_models.py:90-200`) deserialises into a `related` `QueryRequest` (`web/server/query/request/query_request.py:32`), builds a `GroupByQueryBuilder` (`db/druid/query_builder.py`), passes through `AuthorizedQueryClient` for row-level policy filters, and returns pandas DataFrames.
- **Two API stacks.** Flask-Potion REST has 27 resources. Hasura serves Relay for Data Catalog, Field Setup and Data Upload through a proxy at `web/server/routes/api.py:144-176`. A graphene endpoint at `/graphql` serves an empty schema with GraphiQL turned on (`web/server/routes/graphql_api.py:25`).
- **Permissions.** Roles map to permissions. On top sit resource ACLs, groups, and query policies that become Druid filters (`models/alchemy/permission`, `security_group`, `query_policy`).
- **Background work.** Celery 5.4 runs `SendEmailTask` and `SendSMSTask` only (`web/server/tasks/notifications.py`). Alerts are evaluated in the pipeline. The `SchedulerEntry` table has no consumer.

## Frontend

- **Multi-page app.** 19 webpack entries in `web/client/entryPoints/`, each loaded by a Jinja template. There is no client router. Server data arrives through `window.__JSON_FROM_BACKEND`.
- **Component library.** `web/client/components/ui` has 57 in-house modules and a react-styleguidist site.
- **State and data.** Zen immutable models (`web/client/lib/Zen`, about 190 files). `APIService` wraps `$.ajax` in bluebird promises (bluebird appears in 136 files). Relay is pinned to `0.0.0-experimental-c818bac3` and used in 77 files.
- **Charts.** @vx 0.0.195 (26 files). d3 v3 and Plotly 1.22 are loaded from `web/public/js/vendor` at runtime. Maps use react-map-gl 6 with Mapbox.
- **Styling.** Global SCSS. Bootstrap 3 SCSS sits next to Bootstrap 5 JS. jQuery and toastr load on every page.
- **Component style.** 379 files use hooks and 193 use classes. There are no legacy lifecycle methods, so a React upgrade is cheaper than usual.

## Pipeline

- Zeus (git-pinned `py77`, `requirements.txt:80`) runs numbered step scripts. A `.abort_fail` suffix makes a failure fatal.
- `data/pipeline/scripts/process_csv.py` writes Zenysis Base Format as LZ4 JSON lines. `fill_dimension_data` maps raw locations to canonical ones and writes 3M-row gzip shards.
- Druid `index_parallel` creates a timestamped datasource. The web app reads the newest one (`config/harmony_demo/database.py:8`). Validate registers it and keeps the last two.
- Orchestration is a host crontab script (`prod/cron/pipeline.sh`). `process_all:20` swallows failures with `|| true`. The index step waits on a fixed `sleep 120`.
- PyPy forces `numpy==1.15.4` and `shapely==1.8`.

## Infrastructure and CI

- Compose base file with dev, db, local, prod, pipeline and minio overlays, driven by `Makefile` (`COMPOSE_COMMAND`, lines 11-17).
- Runtimes: web runs `python:3.8`, the pipeline runs 3.9, the client builds on `node:18.17`, and the dev image installs Node 14. All four are past end of life.
- GitHub Actions lint changed files and build images (`.github/workflows`). No tests run. `ci/docker/Jenkinsfile` calls Makefile targets that do not exist.

## Security exposures (fix first)

| Exposure | Evidence |
|---|---|
| Hasura runs with no admin secret, and its port is published | `docker-compose.yaml:99`. The Flask proxy forwards no role headers (`web/server/routes/api.py:171`), so every signed-in user is a Hasura admin. |
| Redis has no password, and its port is published | `docker-compose.yaml:86` |
| `DEFAULT_SECRET_KEY` defaults to `changeme` and doubles as the JWT key | `docker-compose.yaml`, `web/server/configuration/flask.py:34` |
| JWT CSRF is off while cookies carry tokens | `web/server/configuration/flask.py:67` |
| Druid metadata password `FoolishPassword`; ZooKeeper and memcached published; JavaScript enabled; extensions fetched from a GitHub `master` branch | `druid_setup/single/environment/common.env`, `druid_setup/extensions/load_extensions.sh:286` |
| Pipeline compose typo `POSTGRES_DB_URI:=` means Alembic never gets the URI | `docker-compose.pipeline.yaml:17` |

## Dead weight to delete before any migration

Installed and never imported: Flask-Admin, graphene and Flask-GraphQL (empty schema), dask, google-cloud-logging, segment-analytics-python, paramiko. On the frontend, papaparse, simple-statistics, d3-random and d3-scale-chromatic have no imports. `query.html` and `grid_dashboard.html` reference bundles webpack does not build.

## Outdated dependencies and their reach

| Dependency | Pin | Reach |
|---|---|---|
| Flask / Werkzeug / Jinja2 | 1.0.1 / 0.16.1 / 2.10.1 | 70 files import flask; private Werkzeug APIs in `web/dev_reloader.py:5`, `web/server/data/druid_context.py:7` |
| Flask-Potion (fork) | git SHA | 51 files, the whole REST layer |
| SQLAlchemy / Flask-SQLAlchemy | 1.3.24 / 2.4.0 | about 200 files |
| flask-user | 0.6.21 | 19 files |
| flask-jwt-extended / PyJWT | 3.25.1 / 1.7.1 | 6 files; `jwt_manager.py:82` breaks on PyJWT 2 |
| py77 (`pylib`) | git SHA | 80 files |
| pydruid | git SHA | 53 files |
| React / ReactDOM | 16.13 | everywhere; 23 `ReactDOM.render` calls |
| react-relay | experimental pin | 77 files |
| bluebird | 3.7 | 136 files |
| @vx | 0.0.195 | 26 files |
| moment | 2.24 | 21 files |
| Druid | 0.23.0 | the warehouse |
| Hasura | v2.11.3 | GraphQL for three apps |
