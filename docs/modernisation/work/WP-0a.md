---
wp: "0a"
title: "Lock down Hasura"
status: review
owner_role: "backend"
instances:
  - name: "backend-1"
    files:
      - graphql/hasura/metadata/versions/latest/tables.yaml
      - graphql/schema.graphql
      - tests/graphql/test_hasura_permissions.py
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
- **`user` permissions** cover the 17 tables the 51 compiled Relay operations touch, with the operations they use (insert, select, update for upserts, delete), all columns, no row filter. Aggregations are allowed only on `category`, `field_category_mapping` and `unpublished_field_pipeline_datasource_mapping`, the three whose aggregates a compiled operation reads. `tests/graphql/test_hasura_permissions.py` pins the full (role, table, operation) set, the `anonymous` columns and the aggregation tables without needing Hasura. That preserves what signed-in users can do today (INV-3) in the UI, and removes their access to the other 28 tracked tables, for example `dashboard`, `alert_definitions`, `case*` and `pipeline_entity*`, which the UI never reads through GraphQL.
- **Not tightened here (deliberate).** A signed-in user without `can_view_data_catalog`, `can_view_fields_setup` or `can_upload_data` can still edit catalog, field setup and upload rows through `/api/graphql`, as on main. Hasura takes one role per request, so per-permission enforcement needs either one role per permission combination or Flask-side parsing of every operation. WP-5e ports the catalog to FastAPI with `can()` checks and retires Hasura; tightening belongs there.
- **`HASURA_GRAPHQL_UNAUTHORIZED_ROLE` is not set (deviation from the phase file).** With it set, a request without the secret is served as that role instead of being refused, which contradicts the phase's own check ("a direct curl to Hasura fails without the secret"). Public-access visitors reach Hasura only through the proxy, which sends the secret plus `X-Hasura-Role: anonymous`.
- **Fail closed.** The proxy returns 503 when `HASURA_ADMIN_SECRET` is empty instead of calling Hasura unauthenticated. Web and worker processes still start, because the worker builds the same Flask config and never calls Hasura. The Compose file refuses to render without the secret (requested below). The `:?` guard matters because Hasura does not treat an empty `HASURA_GRAPHQL_ADMIN_SECRET` as unset: the empty string becomes the secret, and a request carrying an empty `X-Hasura-Admin-Secret` header gets admin. Reproduced on v2.45.8 with the secret set to `''`, on `/v1/metadata`: no header 401, wrong header 401, empty header 200.
- **Metadata stays in the v2 format** under `versions/latest`. I did not copy the old `latest` into a versioned folder as `create_metadata_snapshot.sh` would. Git keeps the history, and phase 5 deletes the folder.
- **Dev secret.** `runserver.py` creates a random secret once in `~/.config/harmony/hasura_admin_secret` (mode 0600) unless `HASURA_ADMIN_SECRET` is set. `start_hasura.sh` recreates the container when the image or secret changes, and binds 127.0.0.1 only.
- **Upgrade and rollback.** v2.45.8 upgrades the v2.11 catalog in place (hdb_catalog version 47 to 48, metadata kept and consistent). There is no `downgrade` command in v2.45 CE. Metadata has no event triggers or actions, so hdb_catalog holds only metadata. Rollback:
  1. Stop Hasura, then run `DROP SCHEMA hdb_catalog CASCADE`.
  2. Start Hasura **2.11.5 or later in the 2.11 line, not 2.11.3**. Keep `HASURA_GRAPHQL_ADMIN_SECRET` set from the same `HASURA_ADMIN_SECRET`, and keep the port unpublished. Rolling back the version must not roll back the lockdown.
  3. Reapply this branch's metadata with this branch's `apply_metadata_snapshot.py`, so the `user` and `anonymous` roles survive.
  4. Keep this branch's proxy code. It works unchanged on 2.11 (Evidence 4, the v2.11.3 run).
- **Anonymous can still smuggle a read.** The proxy's prefix check (`query patchDimensionServiceQuery`) lets a signed-out visitor append a second *query* operation, chosen with `operationName`. Hasura now limits that operation to the `anonymous` columns: dimension `id`, `name` and `description`, dimension-category `id` and `name`, and mapping `id`. That is the data the public query already returns, but the nesting can be arbitrarily deep, because there is no depth or node limit. Two pre-WP-5e options:
  - Have the proxy accept only the hashes of the compiled operation texts, which would also close the prefix check.
  - Use Hasura's allowlist. This does not work here: it rejects the Relay `*_connection` queries the UI sends.
  
  I did neither here. Both change which documents the UI may send, so they need frontend-platform agreement. WP-5e removes the path.
- **Lead-owned files in the diff.** `docs/modernisation/SPEC.md`, `scripts/agents/ownership.py` and decision 0001 come from merging `mig/decisions-0001-ownership`, as the lead instructed. `task_gate.py` flags them until that branch reaches `main`.
- **Deploy order.** The branch code, the Compose change and a `HASURA_ADMIN_SECRET` in each deployment's `.env` must ship together. If the code ships alone, `initialize_new_container.sh` exits on the metadata step (no secret), and the proxy answers 503. This is intended: it fails closed.

## Invariant impact (INV-2, INV-3)

| Area | Before (main) | After (this branch) | Invariant | Status |
|---|---|---|---|---|
| Query results | Druid queries do not pass through Hasura | unchanged | INV-2 | no change |
| Signed-in UI operations (all 51 compiled) | Hasura admin | role `user`; identical responses (Evidence 4) | INV-3 | no change |
| Signed-in access to 28 tables the UI never uses (`dashboard`, `alert_definitions`, `case*`, `pipeline_entity*`, ...) | read and write as admin | none | INV-3 | **tightened on purpose; human acceptance requested** |
| Signed-out visitors, public access on | any query or mutation via a smuggled second operation | reads of 6 public columns only | INV-3 | **tightened on purpose** |
| Hasura metadata API, including `run_sql` (`/v1/metadata`, `/v1/query`, `/v2/query`) | reachable by anyone who could reach port 8088, with no secret | reachable with the secret only, from inside the Compose network; returns 401 without it; the port is not published | INV-3 | **tightened on purpose**. It stays enabled because `apply_metadata_snapshot.py` needs it, so the admin secret is equivalent to database access and must be handled as such |
| Error bodies | admin errors can carry `extensions.internal` (SQL and statement detail) | users are not admin, so it is withheld | INV-3 (information) | reported by the reviewer. My probes (constraint violation, data exception, invalid regex) showed the same body on both sides, so the difference only shows for error classes Hasura reports with `internal` |
| Per-permission checks (`can_view_data_catalog` and others) on GraphQL edits | not enforced | not enforced | INV-3 | unchanged; WP-5e |

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
- [ ] infra (WP-0b, for whichever branch lands second): `tests/infra/test_compose.py` on `mig/WP-0b-ports-secrets-pins` needs `'HASURA_ADMIN_SECRET'` in `BASE_ENV` and `hasura` removed from `PUBLISHED_UNTIL_WP_0A` and `UNPINNED_UNTIL_DECIDED`. This is WP-0b's R7. A trial merge with WP-0b head `0ecd19e` merges `docker-compose.yaml` cleanly. The only conflict is an add/add in `.claude/agent-memory/harmony-infra-engineer/MEMORY.md`, resolved by keeping both lines. With those three edits both suites pass (56 passed), including WP-0b's no-`BROKER_URL` check. Without them, 12 WP-0b tests fail because the config does not render.
- [x] qa: run `verify` on Data Catalog, Field Setup and Data Upload (load and save) on a running stack. Done by qa-0a at f4db7c1: all three pages load and save. The remaining suggestion, moving `scripts/db/hasura/replay_relay_operations.py` into `tests/contract/`, is open for qa.
- [x] infra (round 2, blocks the security fix for item 9; the ownership hook blocked my edit): in `docker-compose.yaml`, switch to the CE image, enable only the graphql and metadata APIs, and correct the empty-secret comment. Update the digest in `tests/infra/test_compose_hasura.py` in the same commit:

  ```diff
     hasura:
  -    image: hasura/graphql-engine:v2.45.8.cli-migrations-v2@sha256:c23e41af28e4c8e27bf6b6e82a5ecdd5b3ba3bb373833f92f5136e25b0ad45c6
  +    image: hasura/graphql-engine:v2.45.8-ce.cli-migrations-v2@sha256:18b39122f207afa4fe7116acaa6484ddac69c2160fde0571e3a27abf924e0bec
       # No published port: only web reaches Hasura, over the Compose network.
       environment:
         HASURA_GRAPHQL_ENABLE_TELEMETRY: 'false'
         HASURA_GRAPHQL_ENABLE_CONSOLE: 'false'
         HASURA_GRAPHQL_DEV_MODE: 'false'
  +      # Relay (/v1beta1/relay) is part of the graphql API; metadata is for apply_metadata_snapshot.py.
  +      HASURA_GRAPHQL_ENABLED_APIS: graphql,metadata
         HASURA_GRAPHQL_MIGRATIONS_SERVER_TIMEOUT: 500
         HASURA_GRAPHQL_DATABASE_URL: ${DATABASE_URL}
  -      # Hasura treats an empty secret as no secret, so refuse to start without one.
  +      # An empty value would make the empty string the secret, so that a request with an
  +      # empty X-Hasura-Admin-Secret header gets admin. Refuse to start without a real one.
         HASURA_GRAPHQL_ADMIN_SECRET: ${HASURA_ADMIN_SECRET:?...unchanged...}
  ```

  ```diff
   # tests/infra/test_compose_hasura.py, lines 20-21
  -    'hasura/graphql-engine:v2.45.8.cli-migrations-v2'
  -    '@sha256:c23e41af28e4c8e27bf6b6e82a5ecdd5b3ba3bb373833f92f5136e25b0ad45c6'
  +    'hasura/graphql-engine:v2.45.8-ce.cli-migrations-v2'
  +    '@sha256:18b39122f207afa4fe7116acaa6484ddac69c2160fde0571e3a27abf924e0bec'
  ```

  Also consider asserting `HASURA_GRAPHQL_ENABLED_APIS == 'graphql,metadata'` in that test. I verified the exact values on the CE image (Evidence 10): relay, `/v1/graphql` and metadata apply all work, and `/v1/config`, pg_dump, `/dev/*`, `/v1/metrics` and `/console` return 404. `/v2/query` and `/v1/query` stay reachable with the secret, as part of the metadata API (see the correction below). The parity replay passes with them. `start_hasura.sh` (dev, mine) already uses the CE digest.
  - infra-4: done on `mig/WP-0a-lock-down-hasura-infra` exactly as written, plus the suggested `HASURA_GRAPHQL_ENABLED_APIS` assertion (Evidence 13).
    **Correction to Evidence 10:** `/v2/query` and `/v1/query` are part of the metadata API, so they stay enabled. With the admin secret, `run_sql` on either returns 200. Without it, `/v2/query` returns 401. Hasura cannot enable `/v1/metadata` without them, so they stay reachable by anyone holding the admin secret.
- [ ] frontend-platform: regenerate six Relay artifacts against the new `graphql/schema.graphql` (role `user`): **Verified by frontend-platform-2 on `mig/WP-0a-lock-down-hasura-frontend`, not committed: the six artifacts are under `web/client/components/**`, which SPEC section 6 assigns to frontend-design. Moved to the frontend-design request below.**
  - `useBatchParentCategoryChangeMutation`
  - `CreateCalculationIndicatorViewMutation`
  - `UpdateCategoryActionMutation`
  - `UnpublishedFieldRowMutation`
  - `useSelfServeMutation`
  - `BatchPublishModalMutation`
  
  Only their Flow input-type declarations change: nested-insert paths into tables `user` cannot write are removed, and v2.45 adds aggregate filters. The operation text, AST, `cacheID` and runtime behaviour are identical (Evidence 11). Nothing breaks meanwhile: no CI step runs `relay-compiler`, and the build reads the committed artifacts. This does not block review.
- [x] frontend-design (done on `mig/WP-0a-lock-down-hasura-design`, 43e4846): in your own branch, run `./node_modules/.bin/relay-compiler` once (no `--watch`; Relay 10.1.0, schema from `relay.config.js`) after `yarn install --frozen-lockfile --ignore-scripts` on Node 24, and commit the result as `WP-0a: regenerate Relay artifacts against the user-role schema`. Expected output: `Updated:` exactly the six artifacts above, `Unchanged: 102 files`; diff stat 6 files, 654 insertions, 1914 deletions. frontend-platform-2 verified this output (log line below). The regeneration is deterministic, so no patch needs handing over. Does not block review.
- [ ] human: accept the deliberate INV-3 change in the "Invariant impact" table. Signed-in users lose GraphQL access to 28 tables the UI never uses, and signed-out visitors lose the smuggled-operation path. Security asked for this acceptance to be recorded.
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
- 2026-10-04 backend-1 round 2, review fixes 1 to 11 except the Compose half of 2 and 9 (requested from infra). Checks:
  - `test_hasura_proxy.py` plus `test_hasura_permissions.py`: 12 passed in a clean environment with only PATH and PYTHONPATH set.
  - `check_role_permissions.py`: 0 failures on v2.11.3, v2.45.8 and v2.45.8-ce, each loaded with the branch metadata.
  - Parity replay: 57 steps, 0 failures, 0 differences on both versions.
  - `test_compose_hasura.py`: 17 passed.
  - Relay compiler 10.1.0: validates every operation against the `user` schema.
- 2026-10-04 infra-4 round 2 compose request applied: CE image, `HASURA_GRAPHQL_ENABLED_APIS: graphql,metadata`, corrected empty-secret comment, test digest updated. Checks:
  - `test_compose_hasura.py`: 17 passed (1 failed before the compose edit).
  - Rendering refuses a missing secret.
  - On a real bring-up: `/v1/version` is `v2.45.8-ce`, and `/console`, `/v1alpha1/config` and `/v1alpha1/pg_dump` return 404.
- 2026-10-04 frontend-platform-2: verified the Relay regeneration on `mig/WP-0a-lock-down-hasura-frontend` (from `c8dcfd6`) but did not commit it, because the artifacts are frontend-design paths; check: Node 24.12 `yarn install --frozen-lockfile --ignore-scripts` exit 0; `relay-compiler` 10.1.0 exit 0, `Updated:` exactly the six named artifacts, `Unchanged: 102 files`; diff stat 6 files, +654 -1914; in every file the last changed line is above `const node` (for example BatchPublishModalMutation: last change at line 543, `const node` at line 639), and no changed line contains `cacheID`, `text`, `kind`, `concreteType`, `selections` or `@relayHash`; the changes are Flow type declarations only: nested-insert input types for tables `user` cannot write (`dimension*`, `dataprep_job`, `*_dimension_mapping`, ...) are removed, `*_aggregate` filters and `*_select_column` enums are added, and update-column enums for tables `user` cannot update become `"_PLACEHOLDER"`; `flow check` output identical to before (19 errors); eslint on the six files (`--no-ignore`) exit 0. Files restored; frontend-design request added.
- 2026-10-04 frontend-design-1: committed the six regenerated Relay artifacts (43e4846, branch `mig/WP-0a-lock-down-hasura-design` from 296cd2b). These are generated files with no visual change, so the `/frontend-design:frontend-design` workflow was not needed. Checks:
  - Node 24.12 `yarn install --frozen-lockfile --ignore-scripts` exit 0.
  - `relay-compiler` 10.1.0 run once, exit 0: `Updated:` exactly the six artifacts, `Unchanged: 102 files`; diff stat 6 files, +654 -1914.
  - In both the old and the new file, every hunk ends above `const node` in all six files. For example, in BatchPublishModalMutation the last change is at line 543 and `const node` is at line 639. No changed line contains `cacheID`, `text`, `kind`, `concreteType`, `selections` or `@relayHash`.
  - `ownership.py who` shows frontend-design for all six.
  - `flow check`: 19 errors, none in a `__generated__` file. Eslint `--no-ignore` on the six exits 0.
- 2026-10-04 backend-1 merged `mig/WP-0a-lock-down-hasura-design` (f0fa8ad, which includes the frontend branch 296cd2b); the WP-file conflict was resolved by keeping both sides. Checks:
  - `test_hasura_proxy.py` plus `test_hasura_permissions.py`: 12 passed.
  - `test_compose_hasura.py`: 17 passed.
  - relay-compiler 10.1.0 `--validate` against the committed `graphql/schema.graphql`: exit 0, so the artifacts are current.

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

10. **Round 2: CE image and enabled APIs.** `hasura/graphql-engine:v2.45.8-ce.cli-migrations-v2@sha256:18b39122f207afa4fe7116acaa6484ddac69c2160fde0571e3a27abf924e0bec` with `HASURA_GRAPHQL_ENABLED_APIS=graphql,metadata`:
    - `/v1/version` returns `{"server_type":"ce","version":"v2.45.8-ce"}`. The startup log has no `license_info` line, which the non-CE tag logs.
    - As `user`, `/v1beta1/relay` and `/v1/graphql` both answer `{"__typename":"query_root"}`, and `apply_metadata_snapshot.py` applies (it uses `/v1/metadata`).
    - `/v1/config`, `/v1alpha1/pg_dump`, `/dev/plan_cache`, `/v1/metrics` and `/console` all return 404.
    - Correction: my `/v2/query` probe sent a GET, which returned 404. infra-4's POST shows that `/v2/query` and `/v1/query` (including `run_sql`) stay enabled as part of the metadata API. They return 200 with the admin secret and 401 without it (Evidence 13).
    - `get_inconsistent_metadata` returns `is_consistent: true`. `check_role_permissions.py` reports 0 failures.
    - Parity replay against this exact configuration, compared with main on v2.11.3: `57 steps, 0 failed`, `0 differences`. The v2.11.3 run with the branch metadata and the same enabled-APIs setting gives the same result.
    - `start_hasura.sh` starts the CE digest bound to `127.0.0.1:8088`.
11. **Round 2: Relay schema as `user`.** `sync_graphql_schema.sh` now runs `check_role_permissions.py --print-schema user`. The secret stays in `HASURA_ADMIN_SECRET`, and the command line carries only `--hasura_host` and `--print-schema`. The regenerated `graphql/schema.graphql` is byte-identical whether it comes from the CE image or the non-CE one.
    - relay-compiler 10.1.0 with graphql 15.3.0, the yarn.lock versions, installed in a scratch directory and run on a copy of `web/client` with `--validate`:
      - against main's schema: exit 0, so the artifacts are current;
      - against the `user` schema: no validation errors, and 6 artifacts are out of date.
    - Regenerating those 6 in the scratch copy changes only Flow input-type lines. No `text`, `cacheID`, `kind`, `concreteType` or `selections` line changes. See the frontend-platform request.
12. **Round 2: the other fixes.**
    - `check_role_permissions.py` pins `graphql-core==3.3.0`, with `check_role_permissions.py.lock` from `uv lock --script` (sha256 for the sdist and wheel).
    - The strengthened `anonymous` assertion fired on the first run: it caught `EditableCalculationQuery`, which reads only public columns and is now an explicit, documented exemption. 0 failures after that.
    - `tests/graphql/test_hasura_permissions.py`: 5 passed. Against main's metadata, 4 fail; the fifth (`backend_only`) passes vacuously because main has no inserts.
    - `anonymous` asking for `dimension.authorizable` gets `field 'authorizable' not found in type: 'dimension'`.
    - Public-access probe on the CE stack: the allowed query returns data, the smuggled mutation gets `no mutations exist`, and the probe row is kept.
    - `apply_metadata_snapshot.py` against a fake Hasura on 127.0.0.1:
      - the first two `/healthz` calls time out (ReadTimeout) and are retried;
      - the POST times out and the script logs `Could not apply metadata ... Read timed out`, then exits 1. Before this fix it crashed with a traceback.
    - `replay_relay_operations.py` refuses, with exit 2 and no rows written, when the flag is missing, when the database is unmarked, and when the database has another comment. The recipe id is now `-424242`.
    - `runserver.py`: a new secret file is created with mode 0600. A 0644 file is refused with a `chmod 600` hint, and the environment is left unset. `HASURA_ADMIN_SECRET` from the environment still wins.
    - pylint 10.00, black `-S` and ruff are clean on every changed Python file.
13. **Round 2, Compose applied** (infra-4, `docker-compose.yaml` on `mig/WP-0a-lock-down-hasura-infra`, dummy env only, `--env-file /dev/null`).
    - The CE digest `sha256:18b39122...` is the manifest list for linux/amd64 and linux/arm64 (`docker buildx imagetools inspect`).
    - `tests/infra/test_compose_hasura.py`: `17 passed`. The new `ENABLED_APIS` assertion failed before the compose edit. ruff and black `-S` are clean.
    - `docker compose -f docker-compose.yaml config` without the secret: exit 1, `required variable HASURA_ADMIN_SECRET is missing a value`, for hasura and web.
    - With a dummy secret: `hasura` ports `[]`, the CE image, and `ENABLED_APIS=graphql,metadata`. The console, dev mode and telemetry are `false`.
    - Bring-up of `hasura` plus a throwaway `postgres:16-alpine` on tmpfs, project `infra4-wp0a-hasura`, random secrets. Both were healthy. `docker compose port hasura 8080` gives no port, and host 8088 is refused. In-network results:
      - `GET /v1/version`: 200 `{"server_type":"ce","version":"v2.45.8-ce"}`.
      - `/v1/graphql`:
        - no secret: 200 `access-denied`, required but not found;
        - empty `X-Hasura-Admin-Secret` header: 200 `access-denied`, invalid;
        - right secret: `{"data":{"__typename":"query_root"}}`.
      - `/v1beta1/relay` with the secret: `{"data":{"__typename":"query_root"}}`.
      - `/v1/metadata` `export_metadata`: 401 without the secret, 200 with it.
      - 404 `not-found` even with the secret: `GET /console`, `GET /v1alpha1/config`, `POST /v1alpha1/pg_dump`, `GET /v1/config`, `GET /v1/metrics` and `GET /dev/plan_cache`. `/v1alpha1/config` is also 404 without the secret.
      - Still enabled, as part of the metadata API: `POST /v2/query` and `POST /v1/query` `run_sql` return 200 with the secret. `/v2/query` returns 401 without it. This corrects the `/v2/query` line in Evidence 10.
    - Torn down with `docker compose down`. No containers or volumes remain for the project.

`pstack:interrogate` was run by the reviewer (rev-0a), with three reviewers, on the proxy and role model. Its findings are folded into the round 2 fixes above.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | changes-requested | 2026-10-04 qa-0a at f4db7c1: every functional claim reproduced, including the browser check on Data Catalog, Field Setup and Data Upload (saves worked). Fix: docker-compose.yaml:105 and WP-0a.md:53 wrongly say an empty admin secret means no secret; an empty value grants admin to an empty header. Notes: wait_for_hasura retries only on ConnectionError; sync_graphql_schema.sh secret on the command line; move replay_relay_operations.py to tests/contract. |
| reviewer | changes-requested | 2026-10-04 rev-0a at f4db7c1: proxy and role metadata correct and minimal. Fix: README .env blocks need HASURA_ADMIN_SECRET (lead); Relay schema still introspected as admin (sync as user, no secret in argv); check_role_permissions must assert anonymous fails every non-public op and drop unused allow_aggregations; replay script must refuse non-disposable DBs and avoid recipe 4242; wait loop retry RequestException; proxy test needs ZEN_ENV and a JWT-role case; note extensions.internal no longer leaks; correct the interrogate sentence. |
| security | changes-requested | 2026-10-04 sec-0a at f4db7c1: lockdown holds against every bypass, header-injection, secret and exposure probe. Blocking: pin graphql-core in check_role_permissions.py (SEC-9). Low: anonymous reads all columns of dimension tables; secret on gq command line in sync_graphql_schema.sh; use the -ce image tag; HASURA_GRAPHQL_ENABLED_APIS graphql,metadata; runserver reuses a secret file without checking mode; rollback plan should name 2.11.5+. Human must record INV-3 acceptance (signed-in users lose GraphQL access to 28 tables). |
