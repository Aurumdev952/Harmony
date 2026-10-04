---
wp: "0a"
title: "Lock down Hasura"
status: review
owner_role: "backend"
instances:
  - name: "backend-1"
    files:
      - graphql/hasura/metadata/versions/latest/tables.yaml
      - web/server/routes/api.py
      - web/server/configuration/flask.py
      - web/server/util/hasura.py
      - web/runserver.py
      - scripts/db/hasura/**
      - tests/web/server/test_hasura_proxy.py
  - name: "infra-4"
    files:
      - docker-compose.yaml
      - tests/infra/test_compose_hasura.py
branch: "mig/WP-0a-lock-down-hasura"
requirements: [SEC-1, SEC-2, SEC-9]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0a: Lock down Hasura

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Hasura metadata grants a `user` role exactly the tables and operations the compiled Relay operations use, and an `anonymous` role read access to the dimension tables behind the public-access query. Check: `scripts/db/hasura/check_role_permissions.py` validates every compiled operation against each role's introspected schema on Hasura v2.11.3 and v2.45.8.
2. The Flask proxy sends the admin secret, `X-Hasura-Role` and `X-Hasura-User-Id` derived from `current_user`, and refuses to call Hasura without a configured secret. Check: `tests/web/server/test_hasura_proxy.py` (red on main, green here), then `scripts/db/hasura/replay_relay_operations.py` through the real Flask app.
3. `apply_metadata_snapshot.py` takes the secret from the environment (never argv), uses `/v1/metadata`, waits for Hasura, and exits non-zero on failure. Check: runs against v2.45.8 with no, wrong and right secret.
4. Local dev Hasura (`start_hasura.sh`, `runserver.py`, `sync_graphql_schema.sh`) runs v2.45.8 pinned by digest, bound to 127.0.0.1, with an admin secret. Check: script runs with and without a secret, rerun and rotation.
5. Compose changes for infra recorded under Requests, verified on a throwaway Compose project built from a scratch copy of `docker-compose.yaml`. Check: no published Hasura port; `docker compose config` refuses a missing secret; Hasura refuses requests without the secret.

**How "fails without the secret" shows up.** The host cannot connect at all: no port is published. Inside the network, the response depends on the endpoint:
- GraphQL endpoints (`/v1/graphql`, `/v1beta1/relay`) answer HTTP 200 with an `access-denied` GraphQL error and no `data`. That is Hasura's behaviour, not a pass.
- `/v1/metadata` answers HTTP 401 `access-denied`.

Checks must therefore assert the `access-denied` error code, not the HTTP status.

All five units are done.

## Decisions and deviations

- **Roles.** The proxy sends `user` for every signed-in user (session, API token with `*` needs, or header login) and `anonymous` for public-access visitors. Site admins also get `user`: the UI needs nothing more, and only the admin secret alone (scripts, console) reaches the `admin` role.
- **`user` permissions** cover the 17 tables the 51 compiled Relay operations touch, with the operations they use (insert, select with aggregations, update for upserts, delete), all columns, no row filter. That preserves what signed-in users can do today (INV-3) in the UI, and removes their access to the other 28 tracked tables, for example `dashboard`, `alert_definitions`, `case*` and `pipeline_entity*`, which the UI never reads through GraphQL.
- **Not tightened here (deliberate).** A signed-in user without `can_view_data_catalog`, `can_view_fields_setup` or `can_upload_data` can still edit catalog, field setup and upload rows through `/api/graphql`, as on main. Hasura takes one role per request, so per-permission enforcement needs either one role per permission combination or Flask-side parsing of every operation. WP-5e ports the catalog to FastAPI with `can()` checks and retires Hasura; tightening belongs there.
- **`HASURA_GRAPHQL_UNAUTHORIZED_ROLE` is not set (deviation from the phase file).** With it set, a request without the secret is served as that role instead of being refused, which contradicts the phase's own check ("a direct curl to Hasura fails without the secret"). Public-access visitors reach Hasura only through the proxy, which sends the secret plus `X-Hasura-Role: anonymous`.
- **Fail closed.** The proxy returns 503 when `HASURA_ADMIN_SECRET` is empty instead of calling Hasura unauthenticated. Web and worker processes still start, because the worker builds the same Flask config and never calls Hasura. The Compose file refuses to render without the secret (requested below). Hasura treats an empty `HASURA_GRAPHQL_ADMIN_SECRET` as unset, which is why the `:?` guard matters.
- **Metadata stays in the v2 format** under `versions/latest`. I did not copy the old `latest` into a versioned folder as `create_metadata_snapshot.sh` would. Git keeps the history, and phase 5 deletes the folder.
- **Dev secret.** `runserver.py` creates a random secret once in `~/.config/harmony/hasura_admin_secret` (mode 0600) unless `HASURA_ADMIN_SECRET` is set. `start_hasura.sh` recreates the container when the image or secret changes, and binds 127.0.0.1 only.
- **Upgrade and rollback.** v2.45.8 upgrades the v2.11 catalog in place (hdb_catalog version 47 to 48, metadata kept and consistent). There is no `downgrade` command in v2.45 CE. Metadata has no event triggers or actions, so hdb_catalog holds only metadata. Rollback: stop Hasura, `DROP SCHEMA hdb_catalog CASCADE`, start v2.11.3, and rerun main's `apply_metadata_snapshot.py`.
- **Lead-owned files in the diff.** `docs/modernisation/SPEC.md`, `scripts/agents/ownership.py` and decision 0001 come from merging `mig/decisions-0001-ownership`, as the lead instructed. `task_gate.py` flags them until that branch reaches `main`.
- **Deploy order.** The branch code, the Compose change and a `HASURA_ADMIN_SECRET` in each deployment's `.env` must ship together. If the code ships alone, `initialize_new_container.sh` exits on the metadata step (no secret), and the proxy answers 503. This is intended: it fails closed.

## Contract changes

None.

## Requests

- [x] infra: apply this diff to `docker-compose.yaml` (blocks unit 5 landing, verified on a scratch copy; evidence below). Done by infra-4 on `mig/WP-0a-lock-down-hasura-infra` (Evidence 9), with `HASURA_GRAPHQL_ENABLE_CONSOLE` and `HASURA_GRAPHQL_DEV_MODE` set to `'false'` explicitly and the healthcheck switched from a TCP probe to `curl /healthz`:

  ```diff
     hasura:
  -    image: hasura/graphql-engine:v2.11.3.cli-migrations-v2
  -    ports:
  -      - 8088:8080
  +    image: hasura/graphql-engine:v2.45.8.cli-migrations-v2@sha256:c23e41af28e4c8e27bf6b6e82a5ecdd5b3ba3bb373833f92f5136e25b0ad45c6
       environment:
         HASURA_GRAPHQL_ENABLE_TELEMETRY: 'false'
         HASURA_GRAPHQL_MIGRATIONS_SERVER_TIMEOUT: 500
         HASURA_GRAPHQL_DATABASE_URL: ${DATABASE_URL}
  +      HASURA_GRAPHQL_ADMIN_SECRET: ${HASURA_ADMIN_SECRET:?HASURA_ADMIN_SECRET must be set}
  ...
     web:
       environment:
         - HASURA_HOST=http://hasura:8080
  +      - HASURA_ADMIN_SECRET=${HASURA_ADMIN_SECRET:?HASURA_ADMIN_SECRET must be set}
  ```

  The worker does not need the secret. `docker-compose.dev.yaml` needs no change: it inherits both. If developers want the console under dev Compose, add `ports: ["127.0.0.1:8088:8080"]` to its `hasura` service only.
- [ ] infra: add `HASURA_ADMIN_SECRET=` to `.env.example`, with a note to generate it (for example `openssl rand -base64 32`) and that it must differ from the other secrets. I could not read `.env.example` (settings deny `.env*`), so check placement yourself.
  - infra-4: not done. Agents cannot read `.env.example` either, so this is left for the human. Every deployment's `.env`, and every developer's for `make up DEV=1`, needs `HASURA_ADMIN_SECRET` before this branch lands, because Compose now refuses to render without it.
- [ ] infra (WP-0b, for whichever branch lands second): `tests/infra/test_compose.py` on `mig/WP-0b-ports-secrets-pins` needs `'HASURA_ADMIN_SECRET'` in `BASE_ENV` and `hasura` removed from `PUBLISHED_UNTIL_WP_0A` and `UNPINNED_UNTIL_DECIDED`. A trial merge of the two branches is clean, and with those three edits both suites pass (56 passed). Without them, 12 WP-0b tests fail because the config does not render.
- [ ] qa: run `verify` on Data Catalog, Field Setup and Data Upload (load and save) on a running stack. This environment has no built web client. Every compiled Relay operation was replayed through the real Flask proxy instead (Evidence 4). Consider adopting `scripts/db/hasura/replay_relay_operations.py` into `tests/contract/`.
- [ ] lead (for routing, outside this WP):
  - The base Compose file also publishes `web` on 5000 (SEC-1). WP-0b's list covers redis, worker and postgres only.
  - Locally, `scripts/create_user.py` fails with bcrypt 4.1+ and passlib ("password cannot be longer than 72 bytes"). bcrypt is unpinned, so a fresh image build can hit it. Pinning it belongs to infra or core.

## Log

- 2026-10-04 backend-1 unit 1: role permissions in metadata; check: `check_role_permissions.py` 51 operations, 0 failures on v2.11.3 and v2.45.8; 52 failures with main's metadata (negative control).
- 2026-10-04 backend-1 unit 2: proxy sends secret, role and user id; check: `pytest tests/web/server/test_hasura_proxy.py` 5 passed (4 failed on main's `api.py`); pylint 10.00 on new files; replay of all 57 steps through the real Flask app, 0 failures, 0 differences from main.
- 2026-10-04 backend-1 unit 3: metadata script reads secret from env; check: no secret exit 1, wrong secret exit 1 (401 access-denied), right secret exit 0 on v2.11.3 and v2.45.8.
- 2026-10-04 backend-1 unit 4: dev Hasura v2.45.8 on 127.0.0.1 with secret; check: no secret exit 1; started bound to `127.0.0.1:8088` with the pinned digest; rerun kept the container; a rotated secret recreated it; dev secret helper stable, mode 0600, env wins.
- 2026-10-04 backend-1 unit 5: compose request verified on scratch copy; check: config refuses missing secret, Hasura publishes no port, host curl to 8088 fails, in-network requests without or with a wrong secret are refused, with the secret answer.
- 2026-10-04 infra-4 compose request applied to `docker-compose.yaml` on `mig/WP-0a-lock-down-hasura-infra`; check: `tests/infra/test_compose_hasura.py` 17 passed (17 failed before the change), real bring-up of hasura plus a throwaway Postgres refused requests without the secret.

- 2026-10-04 backend-1 merged `mig/WP-0a-lock-down-hasura-infra` (fast-forward to e01ab9b, no conflict); check: `pytest tests/web/server/test_hasura_proxy.py` 5 passed, `pytest tests/infra/test_compose_hasura.py` 17 passed.

## Evidence

Environment: throwaway Postgres 16 with all 142 Alembic revisions applied (`flask db upgrade` against a Druid stub), Hasura v2.11.3 and v2.45.8 containers on a private network and 127.0.0.1-only ports, and the web requirements in a Python 3.8 venv matching `Dockerfile_web-server`. Everything was torn down after the run. No real secrets were used. The admin secret was random, held in a 0600 file outside the repo.

1. **Unit tests** (`tests/web/server/test_hasura_proxy.py`): on the branch, `5 passed`. With main's `web/server/routes/api.py` swapped in: `4 failed, 1 passed`. The one that passes guards the unchanged 401 for signed-out users without public access.
2. **Role coverage** (`scripts/db/hasura/check_role_permissions.py`): `51 operations checked, 0 failures` on v2.11.3, on v2.45.8, on v2.45.8 loading metadata through the dev Compose mount (`/hasura-metadata`), and after an in-place v2.11 to v2.45 upgrade. With main's metadata: `52 failures`.
3. **Hasura enforcement on v2.45.8** (direct requests):
   - no secret on `/v1beta1/relay`: HTTP 200 with an `access-denied` error and no `data` ("x-hasura-admin-secret required, but not found");
   - `anonymous` reading `category_connection`: `field 'category_connection' not found in type: 'query_root'`;
   - `anonymous` running a mutation: `no mutations exist`;
   - `user` reading `dashboard_connection`: not found;
   - `user` reading the catalog: succeeds.
   Relay node ids are byte-identical between v2.11.3 and v2.45.8 (`WzEsICJwdWJsaWMiLCAiY2F0ZWdvcnkiLCAicm9vdCJd` for the root category), so `relayIdToDatabaseId` keeps working.
4. **Parity replay** (`scripts/db/hasura/replay_relay_operations.py`): the real Flask app with routes registered (`SERVER_SOFTWARE=gunicorn`), signed in as a non-admin user through `X-Username`/`X-Password`. It ran 57 steps covering all 51 compiled operations, with realistic variables: nested upserts in the upload mutation, dataprep flows, batch publish, deletes.
   - main code + v2.11.3 without secret + main metadata: `57 steps, 0 failed`.
   - branch code + v2.45.8 with secret + branch metadata: `57 steps, 0 failed`, `0 differences` from main after dropping timestamp fields.
   - branch code + v2.11.3 with secret + branch metadata: `57 steps, 0 failed`, `0 differences`.
   - negative control, branch proxy + main metadata: mutations return errors.
5. **Public-access hole closed.** On a deployment with public access enabled, an anonymous visitor sent `query patchDimensionServiceQuery {...} mutation Smuggled { delete_category(...) }` with `operationName: Smuggled`. This passes the proxy's prefix check.
   - main + v2.11: `{"data":{"delete_category":{"affected_rows" : 1}}}`, and the probe row was deleted. Any anonymous visitor could run admin mutations.
   - branch + v2.45.8: `{"errors":[{"message":"no mutations exist", ...}]}`, and the probe row was kept.
   - The allowed `patchDimensionServiceQuery` still returns data on both. Other anonymous queries still get the proxy's 401.
6. **Compose** (scratch copy with the requested diff, project `wp0a-compose`, torn down):
   - `docker compose config` without the secret: `required variable HASURA_ADMIN_SECRET is missing a value`, exit 1.
   - With the secret, published ports: `hasura: []` (nginx 80/443, redis 6379, web 5000 and worker 61234 are unchanged and outside this WP).
   - `docker compose port hasura 8080`: `no port`. Host `curl 127.0.0.1:8088`: connection failed.
   - In-network on `/v1beta1/relay`, where both refusals are HTTP 200 GraphQL errors: no secret is `access-denied`; a wrong secret is `invalid x-hasura-admin-secret`; the right secret returns `{"data":{"__typename":"query_root"}}`; `/v1/version` returns `v2.45.8`.
7. **Metadata script**: no secret gives `HASURA_ADMIN_SECRET must be set`, exit 1. A wrong secret gives `status code 401 ... access-denied`, exit 1. The right secret gives `Successfully applied metadata to .../v1/metadata`, exit 0, and `get_inconsistent_metadata` returns `is_consistent: true` on both versions.
8. **Lint**: black (`-S`) clean. pylint 10.00 on `web/server/util/hasura.py`, `apply_metadata_snapshot.py`, `replay_relay_operations.py`, `runserver.py` and the test. The remaining pylint findings in `api.py` (lines 242, 254, and the unused `ROOT_SITE_RESOURCE_ID`) predate this branch. ruff is clean on the new files. mypy could not run locally: `mypy.ini` loads the `sqlmypy` plugin, which is not installed.
9. **Compose, applied** (infra-4, `docker-compose.yaml` on `mig/WP-0a-lock-down-hasura-infra`, dummy env only, `--env-file /dev/null` so no `.env` is read):
   - `uv run --with pytest pytest tests/infra/test_compose_hasura.py`: `17 passed`; `17 failed` on the unchanged file. Across the base, prod, dev and local overlays it checks that Hasura publishes no port, that an unset or empty `HASURA_ADMIN_SECRET` fails rendering with `HASURA_ADMIN_SECRET must be set`, and that hasura and web receive the same secret. It also checks the pinned image and that the console and dev mode are off. ruff and black `-S` are clean.
   - `docker compose -f docker-compose.yaml config` without the secret exits 1 with `required variable HASURA_ADMIN_SECRET is missing a value: HASURA_ADMIN_SECRET must be set to a random value, e.g. openssl rand -hex 32`, for both hasura and web. With it, published ports are `hasura: []`. The others are unchanged here (WP-0b handles them). The worker gets no secret. Base plus dev plus prod also passes `config --quiet`.
   - Bring-up of the real base `hasura` service with a throwaway `postgres:16-alpine` overlay, project `infra4-wp0a-hasura`, random secrets in 0600 files: both healthy, and the healthcheck is `curl /healthz`. `docker compose port hasura 8080` gives `no port`, and host `curl 127.0.0.1:8088` fails to connect. In-network results:
     - `/v1/graphql` without the secret: `access-denied` ("x-hasura-admin-secret required, but not found"). Hasura answers HTTP 200 with a GraphQL error here, not 401.
     - `/v1/graphql` with a wrong secret: `access-denied`, `invalid x-hasura-admin-secret`.
     - `/v1/metadata` without the secret: HTTP 401, `access-denied`.
     - `/console`: HTTP 404.
     - With the right secret: `{"data":{"__typename":"query_root"}}`.
     - `/v1/version`: `v2.45.8`.
     
     The project was torn down with `docker compose down`, and the containers and network were removed.

Not done: a browser `verify` of the three pages (see the qa request) and `pstack:interrogate`. The proxy change touches no identity flow.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
