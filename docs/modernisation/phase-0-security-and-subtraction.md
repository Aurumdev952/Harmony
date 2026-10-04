# Phase 0. Security and subtraction

Back to [overview](overview.md).

**Goal.** Close the open exposures and delete code and dependencies that nothing uses. This shrinks every later phase. Nothing in this phase changes behaviour for users.

Each unit is one PR.

## 0a. Lock down Hasura

- **Changes.**
  - Set `HASURA_GRAPHQL_ADMIN_SECRET` and `HASURA_GRAPHQL_UNAUTHORIZED_ROLE` in `docker-compose.yaml` and stop publishing port 8088.
  - Have the Flask proxy (`web/server/routes/api.py:144-176`) send the admin secret plus `x-hasura-role` and `x-hasura-user-id` headers from `current_user`.
  - Pass `apply_metadata_snapshot.py` the secret.
  - Upgrade Hasura to v2.45 LTS in the same PR, since v2.11 has been out of support since 2024-09. It is an interim step; phase 5 retires Hasura.
- **Verification.**
  - From the host, a direct `curl` to Hasura fails without the secret.
  - Data Catalog, Field Setup and Data Upload load and save through the proxy (`verify` skill).

## 0b. Close the published ports and default secrets

- **Changes.**
  - Remove the host port mappings for Redis (6379), the worker (61234) and Postgres (5432) from the base Compose file. Keep them in `docker-compose.dev.yaml` only, bound to `127.0.0.1`.
  - Add `requirepass` to Redis.
  - Fail startup when `DEFAULT_SECRET_KEY` is `changeme` or empty.
  - Split `JWT_SECRET_KEY` from `SECRET_KEY` (`web/server/configuration/flask.py:34`).
  - Druid setup:
    - replace `FoolishPassword`,
    - stop publishing ZooKeeper, memcached and Postgres,
    - pin `postgres` and `minio` images,
    - pin the Druid extension downloads to a tag and checksum (`druid_setup/extensions/load_extensions.sh:286`).
- **Verification.**
  - `docker compose config` shows no unintended published ports.
  - Startup with the default key exits non-zero with a clear message.
  - `make up` works with a `.env` that sets real keys.

## 0c. Fix the bugs that are pure mistakes

- **Changes.** Each fix gets a regression test, even before phase 2 exists, as a plain pytest file run locally.
  - `docker-compose.pipeline.yaml:17`: delete the `POSTGRES_DB_URI:=` line. Nothing reads `POSTGRES_DB_URI`; Alembic reads `SQLALCHEMY_DATABASE_URI`, which comes from `DATABASE_URL`.
  - `web/server/routes/dashboard.py:44`: point at the correct blueprint endpoint.
  - `web/server/util/util.py:622`: `is_session_persisted` reads the `accessKey` cookie's persistence instead of `remember_token`.
  - `run_raw_query`: apply the query policy, or restrict callers to service code. Decide this with `pstack:interrogate`.
- **Verification.** A failing test before each fix and a passing one after.

## 0d. Delete dead backend code and dependencies

- **Changes.**
  - Remove from the requirements files: Flask-Admin, graphene-sqlalchemy, Flask-GraphQL, dask, google-cloud-logging, segment-analytics-python, paramiko and its pins, fuzzywuzzy, jellyfish, editdistance.
  - Delete the empty `/graphql` route and its module (`web/server/routes/graphql_api.py`, `web/server/graphql/`).
  - Delete the unused `/api/timeout` route.
  - Delete the Hadoop task templates (`db/druid/indexing/resources/task_templates`, `tuning_configs/on_prem.json`).
  - Point `web/client/util/graphql/zen_environment.js` at the Hasura environment, or delete it.
- **Verification.** Images build. Every page and every Potion resource still responds; use the smoke list in [testing.md](testing.md). `grep` confirms no imports of the removed packages.

## 0e. Delete dead frontend code and dependencies

- **Changes.**
  - Remove from `package.json`: papaparse, simple-statistics, d3-random, d3-scale-chromatic.
  - Remove templates that no route renders: `query.html` and `facilities_map.html`.
  - Remove the `asyncMapChunk` reference from `grid_dashboard.html`.
  - Remove `bootstrap-5.2.0.js` from `layout.html`.
  - Remove bootstrap-select and bootstrap-datepicker from `query_app_vendor_scripts.html`, together with their SCSS.
  - Ask product whether Alerts should be revived or deleted. Today the route renders 404 (`web/server/routes/index.py:69-73`).
- **Verification.** `yarn build` passes. Every page renders without console errors (`verify` skill, all 15 page routes).

## 0f. One CI system and one branch name

- **Changes.**
  - Delete `ci/docker/Jenkinsfile`, or fix its targets if a deployment still depends on it. Ask first.
  - Change the Makefile default `COMMIT?=master` to `main`.
  - Bump the GitHub Actions to their v4/v5 majors.
  - Replace `permissions: write-all` with per-job least privilege.
  - Pin `ubuntu-24.04` across all jobs.
- **Verification.** Every workflow goes green on a PR.

## 0g. Measure browsers before choosing a CSS baseline

- **Changes.** Add a script that summarises user agents from production nginx access logs, sorted by deployment.
- **Data structure.** `BrowserShare = {family, major, share_pct}` per deployment.
- **Verification.** It runs against one deployment's logs. The share of sessions below Chrome 111, Safari 16.4 or Firefox 128 is recorded in the phase 7 decision log. If more than 5% of sessions fall below that line, phase 7 needs a fallback plan before it starts.
