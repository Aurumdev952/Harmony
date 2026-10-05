---
wp: "2c"
title: "API contract recordings"
status: review
owner_role: "qa"
instances:
  - name: "qa-3"
    files: ["tests/contract/**", "tests/db/test_import_data_into_table.py", "docs/modernisation/work/WP-2c.md"]
branch: "mig/WP-2c-api-contract-recordings"
requirements: [QA-2, INV-1, INV-6]
contracts_consumed: [C-4, C-5, C-10]
contracts_changed: []
security_review: false
---

# WP-2c: API contract recordings

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Shape-only JSON Schema inference, merge and diff (`tests/contract/schema.py`), with property tests: soundness against `jsonschema`, merge commutativity and order independence, `diff` empty exactly when shapes are equal, no value or data key leaks into a schema. Check: `pytest tests/contract/test_schema.py`, plus a mutation run that every mutant fails.
2. A disposable `harmony_demo` stack (`tests/contract/stack/`). Check: `stack.sh up` reaches a logged-in API call.
3. Recorder, runner and replay (`cases.py`, `runner.py`, `record.py`, `conftest.py`, `test_replay.py`, `test_cases.py`), with `--dry-run` that needs no network. Check: unit tests, and a record-then-replay round trip on the live stack.
4. Inventory (`INVENTORY.md`) of every endpoint `web/client` and `web/python_client` call, with the owning Flask route, plus the case files and recordings that cover it. `test_catalogue.py` keeps inventory, cases and recordings consistent and scans recordings for PII and secrets. Check: offline suite green; recording on a fresh stack, then replay green twice in a row.
5. Lead request from WP-0c: `/api/field` edge cases and a cookies observation on login, timeout and sign-out.
6. Review fixes (QA and reviewer, changes-requested, 2026-10-04/05): stack secrets, pinned images, internal network, image tags by input hash; enum and set pins, cookie attributes, missing pins and captures reported as diffs, `request_schema` dropped, declared empty maps; populated nested collections; Relay per-operation coverage; inventory gaps; one replay path; history split. Check: offline suite, replay twice on a fresh stack and again on a second fresh stack, from a clean clone of the branch head.
7. Round-3 review fixes (QA and reviewer, changes-requested, 2026-10-06): apiTokens stored through PATCH; catalogue rows seeded so the Relay queries that read them record items, and the 11 deferred Relay mutations recorded; replay reports changed pins as diffs; stale `/graphql` row; maps for resource roles and source date ranges; F10/F11 numbering; remember-me login; Linux-only note; phase-5 notes in `INVENTORY.md`; date-format test row. Check: offline suite, ruff, record twice on fresh stacks with identical output, replay twice on each of two fresh stacks, broken recordings red.
8. Round-4 review fixes (reviewer, changes-requested, 2026-10-04): merge `mig/integration` and drop the bcrypt shim image (F3 fixed by WP-0b); merge backend's F12 fix and correct the token case notes; F13 rewritten around the upsert remedy and the real code path; a seeded published field so field-page queries pin datasource and dimension mappings; the unpublished-field table queries run after the category mapping is restored; empty connections enforced by `test_catalogue`; capture errors never echo values; token dates sent as the client does. Check: offline suite, ruff, record twice on fresh stacks with identical output, replay twice on each of two fresh stacks, a broken recording red.
9. Final round (lead, 2026-10-05): merge core's F13 fix (`mig/WP-2c-api-contract-recordings-core` at `effacb8`); re-record `BatchPublishModalContentsQuery` and the unpublished-field cases on a fresh stack; drop the empty-connection annotation; F13 text to core's final design; core's three follow-ups under Requests. Check: `tests/db` 9 passed (6 failed with the pre-fix `utils.py`), offline suite, dry run, ruff, record twice on fresh stacks with identical output, replay twice on each of two fresh stacks, a broken recording red.

Files: QA's commits touch `tests/contract/**`, this file, QA memory, and one line of the shared `tests/db/test_import_data_into_table.py` (ruff S608). The branch also carries production fixes merged from their owners' branches: backend's F12 (`web/server/routes/views/users.py`) and core's F13 (`db/postgres/utils.py`).

## Contract changes

None. This WP records the existing Flask contract; it changes no producer.

## Requests

None of these block WP-2c; each comes from a finding below or from the review.

- [x] infra (WP-2f): add pinned `hypothesis` and `jsonschema` (and `requests`, which the replay uses) to the `dev` group, register the `stack` marker in `[tool.pytest.ini_options]`, add `tests/contract` to `testpaths`, and run `pytest tests/contract -m "not stack"` on every PR and `-m stack` in the job that brings the stack up. Until then `tests/contract/conftest.py` registers the marker itself and the commands in `INVENTORY.md` use `uv run --with`.
  - 2026-10-04 qa-3: done by WP-2f, except the `-m stack` job. `pyproject.toml` pins `hypothesis`, `jsonschema` and `requests`, registers the `stack` marker and collects `tests/`, and `ci/pytest_suites.sh` runs each suite with `-m 'not stack'`. `conftest.py` no longer registers the marker, and `INVENTORY.md` uses `uv run --locked`. Running the replay in CI belongs to the overlay request below.
- [ ] infra: own the stack as an overlay on `docker-compose.yaml`, shared with WP-2e (Playwright), WP-1a (perf) and `verify`. The overlay must provide:
  - a unique project name and loopback port per run (`CONTRACT_PROJECT`, `CONTRACT_WEB_PORT`);
  - every secret generated per stack into a mode-600 file outside the repo (admin password, Postgres, `REDIS_PASSWORD`, `HASURA_ADMIN_SECRET`, `DEFAULT_SECRET_KEY`, `JWT_SECRET_KEY`), passed to web, web-init, worker, redis and hasura;
  - Postgres on tmpfs with `flask db upgrade` and a seeded site admin;
  - a Druid stand-in (or a small real Druid) so config import and seed migrations run;
  - a mail sink and an `internal: true` network with one forwarder publishing web, so nothing reaches Mailgun, Urlbox or a CDN;
  - Hasura metadata applied after start, and the thumbnail cache seed from `stack/seed_cache.py`;
  - images pinned by digest and the web image tagged by a hash of its inputs.

  `tests/contract/stack/` does all of this today and can move as is.
- [ ] qa (WP-2b): `tests/authz/stack.sh` on `mig/WP-2b-authz-suite` drives `tests/contract/stack/compose.yaml` directly with one generated password. After this WP the compose file needs `CONTRACT_WEB_IMAGE` and six generated secrets, so call `tests/contract/stack/stack.sh up|down|env` with `CONTRACT_PROJECT`, `CONTRACT_WEB_PORT` and `CONTRACT_USERNAME` set instead (the credentials file still carries a `CONTRACT_PASSWORD=` line, which `tests/authz/http/stack.py` already reads). Whichever of 2b and 2c merges second adapts.
- [x] ~~infra~~ qa: WP-0b's `requirements.txt` pin of `bcrypt==4.0.1` fixes F3. When it lands, delete `tests/contract/stack/Dockerfile` and build `docker/web/Dockerfile_web-server` directly.
  - 2026-10-04 qa-3: this was misaddressed, since the stack is qa's. Done in unit 8 (`f7e4895`). WP-0b is in the base, so `stack.sh` builds `Dockerfile_web-server` and exports it as `CONTRACT_WEB_IMAGE` (`harmony-contract-web-server:<hash of requirements*.txt and the Dockerfile>`). The shim Dockerfile and its `--build-context` base pin are gone, because WP-0b pins the base image by digest in the Dockerfile itself.
- [ ] infra: object storage (minio) settings the web app accepts, added to the stack, so the data digest and data-upload routes can be recorded (deferred rows in `INVENTORY.md`).
- [ ] data-platform or infra: a small Druid with `harmony_demo` data for the stack, so `POST /api2/query/hierarchy` can be recorded (it 500s under the offline mock client) and query cases stop depending on `ZEN_OFFLINE` (see "What phase 5 needs").
- [ ] frontend-platform: fix the raw-data export payload (F1). Then re-record `query.table.disaggregated.client_payload`.
- [ ] frontend-platform: confirm whether the services behind F2 are dead code, and delete them or ask backend for the routes.
- [ ] backend: return 400 from `POST /api/validate_self_serve_upload` for a non-zip file (F5).
- [ ] backend: make `web/python_client` log in through `POST /api2/authentication/login` with `email` and use the bearer token (F7).
- [ ] backend: default `EMAIL_HOST` to nothing and skip sending when mail is unconfigured (F6).
- [ ] backend: make `PATCH /api2/user/<id>` return the updated user (F8).
- [ ] backend: answer `GET /api2/dashboard/<id>?legacy=1` with a 404 or the current spec when there is no legacy specification (F9).
- [ ] backend (WP-0h): the role-map endpoints (F10) both 500 on any assignment and delete `Role` rows on clear.
- [ ] backend (WP-0i): `/api2/storage/retrieve` for an unknown slug is a 500, and a cache miss sends a render-bot JWT to Urlbox in a URL (F11).
  - Reported by qa-0i (2026-10-04) against `mig/WP-0i-render-route-guards` at `9059571`. When WP-0i merges, `storage.retrieve.unknown_slug` becomes a 404, which closes F11, and an outsider gets 403 instead of 401.
  - `storage.retrieve.cached` then breaks. The cache key becomes `thumbnail:v2:<dashboard resource_id>:<sha256 of the policy digest>`, so the request never reads `stack/seed_cache.py`'s `thumbnail_contract-dashboard`. It falls through to Urlbox, which 500s because the stack has no egress.
  - Whichever of WP-0i and WP-2c merges second must seed the v2 key, re-record both cases, and give the reason in its log. `stack.sh up` runs `seed_cache.py` once, before any case, and the dashboard's resource id only exists after `dashboard.create`. So an HTTP-free seed at stack start cannot know the key. Seeding needs either a non-HTTP step that the runner calls after `dashboard.create` (for example, `docker compose exec web python tests/contract/stack/seed_cache.py <resource_id>`), or a resource id predicted from a fresh database's sequence. The predicted id breaks on a reused stack.
- [x] backend or QA (WP-0a): record the 11 deferred Relay mutations. Done in unit 7: `stack/seed_catalog.py` seeds the rows they edit, and all 51 Relay operations are recorded. WP-0a's `replay_relay_operations.py` still carries its own variables. Whichever WP touches Relay next should make one of the two the source.
- [x] backend: `POST /api2/user/<id>/generate_api_token` returns a token it does not store (F12). Either store it there, or document that the caller must save the user. A script that calls the route alone gets a token that never authenticates.
  - 2026-10-04 backend-2c: done at `48ff9a3`. The route stores the token. See "Backend support: F12 and F13".
- [x] core: `POST /api/import_self_serve` deletes rows in tables it does not import (F13). Fix it by upserting the export's rows and deleting only the rows the export lacks, in one transaction, with no `TRUNCATE ... CASCADE` (see F13). Then re-record `graphql.BatchPublishModalContentsQuery` and the unpublished-field cases.
  - 2026-10-04 backend-2c: failing tests are in at `d23076f`. The fix is in `db/postgres/utils.py` (core), so a core instance applies it on `mig/WP-2c-api-contract-recordings-core`. Tick this line when that branch merges.
  - 2026-10-04 core-2c: fixed at `d016bce` on `mig/WP-2c-api-contract-recordings-core`, which merges back through backend's branch. Ticked at the lead's request; the merge is still pending. Two defects in the proposed patch were fixed: delete-before-upsert cascaded into exported rows, and sequences were set before the import could still fail. See "F13: core review and fix".
  - 2026-10-04 qa-3: once that branch merges, QA re-records and drops the `empty connection` annotation from the BatchPublish row in `INVENTORY.md`. `test_catalogue` fails until both happen.
  - 2026-10-05 qa-3: merged at `84b8cf7`. Re-recorded on fresh stacks: six recordings now pin the unpublished-field mapping items, and the annotation is gone. See unit 9.
- [ ] core: export the data-catalog tables in one `REPEATABLE READ READ ONLY` transaction. `export_tables_to_zip` copies each table in its own autocommit transaction, so an export taken during edits can be inconsistent, and the fixed import now refuses such an archive (core's F13 follow-up).
- [ ] core: COPY maps CSV columns by position, so a target whose column order differs from the source (a schema built by `create_all` against one built by Alembic) misloads. Map columns by name from the CSV header. This predates F13 (core's F13 follow-up).
- [ ] backend: `POST /api/import_self_serve` waits 120 s for the import subprocess. When the import outlives it, `communicate` raises, the `with Popen` block waits for the child anyway, and the route can answer with an error for an import that then commits (`web/server/routes/api.py`, core's F13 follow-up).
- [x] core: `ci/lint_python.sh mig/integration` format-checks every Python file the branch changes, and `db/postgres/utils.py` would be reformatted (three `with` blocks and one call). Run `ruff format` on it in a format-only commit, or tell the lead to accept the red format step. Found by qa-3 on 2026-10-05.
  - 2026-10-05 core-2c-2: done in a format-only commit on `mig/WP-2c-api-contract-recordings-core-2` (see Log). The format step now passes on `db/postgres/utils.py`.
- [ ] backend: the same lint step fails on the F12 files. `web/server/routes/views/users.py:432` is E712 (`APIToken.is_revoked == False`; `APIToken.is_revoked.is_(False)` keeps the SQL), and `users.py` and `web/server/api/user_api_models.py` would be reformatted. Found by qa-3 on 2026-10-05.

## Log

- 2026-10-04 qa-2 unit 1: shape-only JSON Schema infer/merge/diff with property tests; check: `pytest tests/contract/test_schema.py` 18 passed (seeds 1-3 too); mutation run killed 6 of 6 mutants after adding the required-drift example.
- 2026-10-04 qa-2 unit 2: disposable stack in `tests/contract/stack/`; check: `stack.sh up` from nothing reaches `web is up`, login returns 200, only the web port published on loopback.
- 2026-10-04 qa-2 unit 3: recorder, runner, replay, dry-run; check: `pytest tests/contract/test_cases.py` green, dry-run lists every case without network, record-then-replay round trip green.
- 2026-10-04 qa-2 unit 4: inventory, cases, recordings, catalogue checks; check: offline suite green; replay green twice on the recording stack and on a second fresh stack; a deliberately broken recording turns replay red.
- 2026-10-04 qa-2 unit 5 (lead request from WP-0c): `/api/field` edge cases and the cookies observation; check: unit tests green, fresh-stack record and replay.
- 2026-10-04 qa-2: status review; QA and reviewer verdicts changes-requested.
- 2026-10-05 qa-2 unit 6: review fixes (see Plan 6 and "Review fixes" below); merged `mig/integration` (WP-0a, WP-0c, decision 0003/0004; `.playwright-mcp` gone, `git ls-files .playwright-mcp` empty); re-recorded on the merged code: exactly three recordings changed, all from WP-0c (`auth.timeout` now clears the JWT and CSRF cookies, `field.info.unknown_id` 404, `field.info.over_cap` 400). History rewritten before any push: the mixed commit 501337e is now a harness commit followed by an inventory-and-recordings commit; the first review's verdict rows are carried in the WP file. Checks under Evidence.
- 2026-10-05 qa-2: status review.
- 2026-10-04 qa-3 unit 7: resumed after the host reboot lost qa-2's session and carried its uncommitted round-3 work over. Round-3 fixes R1-R7, plus the client's `%%` search pattern, a `next_run` seed, and findings F12 and F13; commits `787f6b9` and `dc935f5`. Check: ruff clean; offline `51 passed`; dry run `231 cases, 0 problems`; two recordings on fresh stacks, identical; replay `282 passed` twice on each of two fresh stacks; two broken recordings red; stack down. Status review.
- 2026-10-04 backend-2c (supporting, F13): failing tests `tests/db/test_import_data_into_table.py` (3 failed, 1 passed at `00e5047`) and the proposed core patch `WP-2c-evidence/F13-db-postgres-utils.patch` (4 passed with it); handed to core through the lead.
- 2026-10-04 backend-2c (supporting, F12): `issue_api_token` stores the generated token and the route calls it, commit `48ff9a3`. Checks: the new `tests/web/test_api_token_issue.py` failed against the old behaviour (`check_token_validity` False) and passes, 2 of 2, including the admin app's later save and revoke. `tests/web` gives 70 passed, 1 failed; the failure is the existing `test_graphql_endpoint_removed` (`flask_migrate` is missing from the uv env, also at `00e5047`). The contract offline suite gives 51 passed, and the dry run reports 231 cases, 0 problems. Replay on a fresh stack: 231 passed, twice. The live F12 check passed. ruff and mypy on the changed files are clean. Stack down.
- 2026-10-04 qa-3 unit 8: round-4 fixes S1-S9. Merged `mig/integration` (`cbaf776`) and backend's F12 branch (`fd187c8`); commits `f7e4895`, `24cc64c` and `ed1a07c`. Check: ruff clean; offline `57 passed`; dry run `234 cases, 0 problems`; two recordings on fresh stacks, identical; replay `291 passed` twice on each of two fresh stacks; one broken recording red; stack down. Status review.
- 2026-10-05 qa-3 unit 9: merged core's F13 branch at `effacb8` (`84b8cf7`; conflicts only in this file, both sides kept). `tests/db` 9 passed, and 6 failed with `b6e49b8`'s `db/postgres/utils.py`. Re-recorded on a fresh stack: six recordings changed, each only by an empty list becoming an item schema, and the BatchPublish annotation is dropped. Replaced the f-string `SELECT` in `tests/db/test_import_data_into_table.py` with `psycopg2.sql.Identifier`, and cleared ruff in core's two evidence scripts (S608 noqa on constant SQL, an `assert` turned into `SystemExit`). The changed-files lint still fails on core's and backend's production files: two requests added. Check: ruff clean on QA's files and the evidence scripts; offline `57 passed`; dry run `234 cases, 0 problems`; two recordings on fresh stacks, identical; replay `291 passed` twice on each of two fresh stacks; one broken recording red; stack down. Status review.
- 2026-10-04 core-2c (supporting, F13): reviewed backend's patch as owner and found two defects (a cascade into exported rows, and sequences rewound by a failed import), each shown by a new test that fails with the patch. Fix `d016bce`: one transaction; upsert referenced tables, then delete absent rows; empty and reload the leaves; count check; non-lowering sequences, set last. Merged backend's `8804af2`. Checks: `tests/db` 9 passed, 4 of 4 mutations killed, ruff and mypy clean on the changed files, golden 269 passed, perf old vs new recorded under "F13: core review and fix". `scripts/data_catalog/import_db_tables.py` (lead) needs no change.
- 2026-10-05 core-2c-2 (supporting, lint): ran `ruff format db/postgres/utils.py`. It changes the layout only: three `with` statements become parenthesised context managers, and one `cursor.execute` call is joined onto one line. The AST under the project's CPython 3.9.25 is equal before and after. Checks: `ruff check` and `ruff format --check` are clean on the file, and `ZEN_ENV=harmony_demo pytest tests/db` gives 9 passed. `ci/lint_python.sh mig/integration` no longer reports this file. It still fails on backend's F12 files (`users.py:432` E712, and the format of `users.py` and `user_api_models.py`), which is the open backend request.

## Review fixes

| # | Fix | Where |
|---|---|---|
| 1 | Images are always built (layer cache) and tagged by a hash of `requirements*.txt` and both Dockerfiles; no shared global tag. `stack/Dockerfile` names WP-0b as its removal trigger. | `stack/stack.sh` `build_images`, `stack/Dockerfile` |
| 2 | Every secret generated per stack and passed to web, web-init, redis and hasura. `compose.redis-auth.yaml` (requirepass) and `compose.hasura-secret.yaml` (admin secret) are added when the checked-out code reads `REDIS_PASSWORD` (WP-0b) or `HASURA_ADMIN_SECRET` (WP-0a), so the stack starts before and after either lands, in any merge order. On this branch WP-0a is merged and the Hasura overlay is active. There is no worker service: Celery runs tasks eagerly in web here. Overlay request to infra above. | `stack/compose*.yaml`, `stack.sh` |
| 3 | Secrets file in `$XDG_RUNTIME_DIR` (else `~/.local/state/harmony-contract`, mode 700), read line by line for known names only, refused unless owned by the user with mode 600 (also in `runner.Credentials`). All images pinned by digest; the base build pins `python:3.8` through `--build-context`. `CONTRACT_PROJECT`/`CONTRACT_WEB_PORT` documented per CI job. All services on an `internal: true` network; a forwarder publishes web. `create_user.py` no longer logs passwords on integration, so the `sed` redaction and the F4 request are gone. | `stack/`, `runner.py`, `INVENTORY.md` |
| 4 | `ruff format` at 88; replay marked `stack`; dev-group request to infra. | all `.py`, `test_replay.py`, `conftest.py` |
| 5 | Nested collections populated: pipeline runs seeded; role and group kept alive until the dashboard shares with them; new reads after `resource.update_roles` (`resource.roles.after_update`, `user.get.with_acls`, `group.find_by_name.with_acls_and_roles`); alert filters non-empty. Corrected in round 3: `user.get.with_api_token` recorded an empty `apiTokens` until `user.update.persist_api_token` stored the token (F12). | `cases/` |
| 6 | `pin` takes `[]` and `{*}` tokens and records the sorted value set: user status, resource types, role names, configuration keys, granularities, policy types, alert checks. `DASHBOARD` vs `dashboard` is now a diff. | `cases.pin_value` |
| 7 | Cookies: `cleared`, `session` or `persistent` (Max-Age or Expires), `httponly`, `secure`, `samesite=<lowercase>`, `path`, `domain`. | `cases.describe_set_cookie` |
| 8 | A dropped pinned field is `pinned /x: ... recorded, missing now`; a failed capture is reported after the shape diff. `request_schema` is gone from recordings (request bodies live in the case files). | `cases.observe`/`compare`, `runner.run` |
| 9 | A declared map that is empty stays a map (`maxProperties: 0`); `role.num_users` and `digest_overview` declare `maps: ["$"]`. | `schema.infer`, `cases/` |
| 10 | Inventory: `GET /api2/query/table[/disaggregated]?h=` with 200/400/404 cases; the four `/dashboard/...` pdf and jpeg share links listed as deferred (Urlbox); a Relay table of all 51 operations, 40 recorded and 11 deferred, checked by `test_catalogue`; `storage/retrieve` recorded (seeded hit and unknown-slug 500); the configuration-list caller corrected; seed routes for pipeline runs listed. | `INVENTORY.md`, `cases/` |
| 11 | Phase-5 paragraph rewritten; pin counts corrected; bug notes on F2/F5 cases; python_client's unreachable fallback noted. | this file, `cases/` |
| 12 | Mixed commit split; `record.py` records and dry-runs only (replay is `pytest -m stack`); dry-run and `test_catalogue` share `catalogue.py`. | history, `record.py`, `catalogue.py` |

## Round-3 fixes

| # | Finding | Fix | Evidence |
|---|---|---|---|
| R1 | apiTokens empty (QA, reviewer) | `user.generate_api_token` captures the token's `$uri` and `id`. `user.update.persist_api_token` then PATCHes the user with the token, as the admin app does (`UserViewModal/index.jsx:321`). `user.get.with_api_token` now pins the item shape: `$uri`, `created`, `id`, `isRevoked`, `revoked` and `token: null`. F12 logged. | `recordings/user.get.with_api_token.json` |
| R2 | Nine Relay queries recorded empty connections (reviewer) | `stack/seed_catalog.py` (run by `init.sh`) seeds a dimension, two pipeline datasources, an unpublished field with mappings, a Dataprep flow and a self-serve source. The unpublished-field table queries now send `%%`, as the client does. The `ALL_SOURCES` pipeline-run seed carries `next_run`. At `fa72fe0`, 14 Relay recordings had an empty top-level connection; 13 now record items. The 14th, `BatchPublishModalContentsQuery`, stays empty because `self_serve.import.exported_zip` deletes the seeded datasource mapping (F13). Corrected in round 4: `UnpublishedFieldTableRowsQuery` pins the same node's scalars, but no recording pins the unpublished datasource-mapping item shape until F13 is fixed. Closed in unit 9: with core's fix merged, `BatchPublishModalContentsQuery` records the field and its mappings. The 11 deferred mutations are recorded too, so 51 of 51 Relay operations are covered. | `/tmp/wp2c_edges.py` over the recordings; `INVENTORY.md` Relay table |
| R3 | A changed pinned value raised instead of a diff (reviewer) | During replay, `observe` never raises: it replaces an unsafe value with a marker. `record.py` passes `recording=True`, which still refuses unsafe pins. New test: `test_a_replay_reports_an_unsafe_pinned_value_without_echoing_it`. | broken-recording run below |
| R4 | Stale `POST /graphql` row (reviewer) | Row deleted. WP-0d removed `r/graphql_api.py` and `zen_environment.js`. | `INVENTORY.md` |
| R5 | `data_upload.sources_date_ranges` and `resource.roles*` keyed by data (reviewer, QA) | `maps: ["$"]` and `maps: ["$.groupRoles", "$.userRoles"]`. | the three recordings |
| R6 | F10/F11 numbering (reviewer) | Both case notes say F10. | `cases/20-directory.json`, `cases/95-cleanup.json` |
| R7 | Non-blocking (reviewer) | `auth.login.cookie.remember_me` records `accessKey` as persistent. The Linux-only note and the phase-5 section are in `INVENTORY.md`. The `date` row WP-2f asked for is in `test_schema.py`. | `INVENTORY.md`, `recordings/auth.login.cookie.remember_me.json` |

## Round-4 fixes

| # | Finding | Fix | Evidence |
|---|---|---|---|
| S1 | Shim image still built after WP-0b (reviewer) | Merged `mig/integration` at `327980c` (`cbaf776`). Deleted `stack/Dockerfile`. `build_images` builds and exports the web-server image directly. F3 is marked fixed, and the misaddressed infra request is closed. | `f7e4895`; replay below |
| S2 | F13 remedy and code path wrong (reviewer) | F13 rewritten: the route runs `scripts/data_catalog/import_db_tables.py`, whose `DATA_CATALOG_TABLE_NAMES` sets the tables and their order. The remedy is the upsert-then-delete-absent fix core is building. DELETE without CASCADE is ruled out, because the dependent foreign keys are `ON DELETE CASCADE`. | Findings |
| S3 | Limits incomplete; BatchPublish row overstated (reviewer, QA) | `seed_catalog.py` seeds `contract_seeded_field`, a published field in `root` with a datasource mapping and a dimension mapping. New cases cover it: `FieldAboutPanelQuery.seeded_field`, `FieldDetailsPageQuery.seeded_field` and `DirectoryTableContainerQuery.root`. `patchFieldMetadataServiceQuery`, `QueryBuilderQuery`, `useFieldHierarchyRootQuery`, `CreateCalculationIndicatorViewQuery` and `DataStatusPageSelfServeQuery` now carry the mappings. The two unpublished-field table queries run after `CategoryInputMutation`, which restores the category mapping the import deletes, so that item shape is pinned. The BatchPublish row reads `recorded (empty connection, F13: ...)`, and the case note and R2 no longer claim its datasource-mapping shape is pinned. | the new and changed recordings; Limits |
| S4 | Thumbnail v2 note (reviewer) | The note now says `seed_cache.py` runs before any case, so the second WP to merge needs a non-HTTP step after `dashboard.create`, or a predicted resource id. | Requests, F11 |
| S5 | Capture errors echoed the value (reviewer) | `capture_value` wraps a failed `#id` or `#relay` conversion in `ValueError("value at <pointer> is not a <transform> reference")`. New test: `test_a_failed_capture_transform_does_not_echo_the_value`. It failed before the fix for `#id`, because the message contained the value. | `test_cases.py` |
| S6 | seed_catalog docstring (reviewer) | Corrected: `useSelfServeMutation` creates a self-serve source for an existing pipeline datasource. | `stack/seed_catalog.py` |
| S7 | Empty-connection scan not enforced (reviewer) | `catalogue.empty_connection_problems`, run by `test_catalogue` and the dry run. If every recording of a Relay operation has an empty `edges`, its row must say `recorded (empty connection, <reason>)`. A row that says so while a recording has items is reported as stale. Three synthetic tests cover the rule, and one test checks the real inventory. | `test_catalogue.py` |
| S8 | Token dates (reviewer, optional) | `user.generate_api_token` captures `created` and `revoked`, and `user.update.persist_api_token` sends them back as `APIToken.serialize()` does. | `cases/20-directory.json` |
| S9 | F12 fixed by backend (lead) | Merged `mig/WP-2c-api-contract-recordings-backend` at `8804af2` (`fd187c8`). The `user.generate_api_token`, `user.update.persist_api_token` and `user.get.with_api_token` notes now say the route stores the token and the PATCH is the admin app's save. The recordings are unchanged. | `cases/20-directory.json` |

## Evidence

The final round was re-run in full on 2026-10-05 by qa-3 at `84b8cf7` plus the unit-9 changes. That tree carries `mig/integration` `327980c`, backend's `8804af2` and core's `effacb8`. Live runs used a disposable stack with `CONTRACT_PROJECT=wp2c-r5 CONTRACT_WEB_PORT=58781` and `eval "$(tests/contract/stack/stack.sh env)"`. The stock image built as `harmony-contract-web-server:f46617f35db7`, the same as in round 4. All commands ran under `uv run --locked`.

- **Static**: `ruff format --line-length 88 --check tests/contract` reports 17 files already formatted. `ruff check tests/contract tests/db db/postgres/utils.py` reports all checks passed. The CI step `ci/lint_python.sh mig/integration` lints the 26 Python files the branch changes. QA's files and core's evidence scripts pass it (unit 9 fixed an S608 in `tests/db`, two in `F13-perf.py` and an S101 in `F13-mutate.py`). It still fails on the merged production files: E712 at `users.py:432`, and `ruff format` would change `db/postgres/utils.py`, `users.py` and `user_api_models.py`. Those are owner requests above.
- **F13 fix**: `ZEN_ENV=harmony_demo pytest tests/db` reports `9 passed`. With `db/postgres/utils.py` from `b6e49b8` (before the fix) it reports `6 failed, 3 passed`.
- **Dry run**: `python -m tests.contract.record --dry-run` reports `234 cases, 0 problems`.
- **Offline suite**: `pytest tests/contract -m "not stack"` reports `57 passed, 234 deselected`. With the old BatchPublish row restored, `test_catalogue` fails with `BatchPublishModalContentsQuery: marked empty connection but a recording has items`.
- **Properties**: `test_schema.py` passes 22 tests under `--hypothesis-seed` 1, 2 and 3.
- **Recording is reproducible**: all 234 cases were recorded on a fresh stack. Then `stack.sh down`, `stack.sh up`, and a second recording. Neither run had an error or skip, and `diff -r` between the two sets is empty.
  - Against round 4, six recordings changed, all because the import keeps the seeded mappings: `BatchPublishModalContentsQuery`, `CategoryInputMutation`, `UnpublishedFieldTableRowsQuery`, `UnpublishedFieldTableRowsPaginationQuery`, `UpdateCalculationActionMutation` and `UpdateCategoryActionMutation`.
  - Every removed line in that diff is a `"maxItems": 0` (eight in all), each replaced by an item schema. No key, type or pin changed elsewhere.
  - `BatchPublishModalContentsQuery` now pins the publishable field and its category and datasource mapping items.
- **Replay, same stack**: `pytest tests/contract` (offline plus `stack`) reports `291 passed`, twice back to back.
- **Replay, new stack**: after `stack.sh down` and `stack.sh up`, the same command reports `291 passed`, twice.
- **Broken recording turns red**: `pipelineDatasourceId` was renamed to `datasourceKey` in `recordings/graphql.BatchPublishModalContentsQuery.json`. `pytest -m stack` then reports `$.data.publishableFields.edges[].node.unpublishedFieldPipelineDatasourceMappings[]: missing key 'datasourceKey'`, with `1 failed, 233 passed`. The file was restored, and `diff -r` against the recorded set was empty again.
- **Isolation**: only `forward` publishes a port (`127.0.0.1:58781`). `stack.sh down` removed the secrets file and left no `wp2c-r5` container.
- **No secrets or PII in fixtures** (INV-6): `test_recordings_hold_no_values_that_look_like_secrets_or_pii` scans all 234 recordings. The re-recording added no pinned value.

Limits:
- 17 of 145 routes are deferred, each with its reason in `INVENTORY.md`: object storage, Dataprep, Urlbox rendering, `hierarchy` under the mock Druid, dead client code, and a static GeoJSON asset. No Relay operation is deferred.
- Other lists are empty in every recording because no case or seed fills them:
  - mapping lists on fields that the cases create or delete: `CreateCalculationIndicatorViewMutation*` (no mappings at creation), `FieldAboutPanelQuery` and `FieldDetailsPageQuery` on `contract_field`, `DirectoryTableContainerQuery` on `contract_category`, and `DeleteFieldModalMutation*`'s `fieldCategoryMapping`. The seeded-field and root cases pin these shapes.
  - Dataprep jobs, file summaries and category children.

  `/tmp/wp2c_empty.py` lists every one.
- Query responses come from Harmony's offline mock client, so they pin shapes, not numbers. Numbers belong to the golden suite (WP-2a). See "What phase 5 needs" in `INVENTORY.md`.

## What phase 5 needs (QA-2)

Moved to the "What phase 5 needs" section of `tests/contract/INVENTORY.md`, next to the suite it describes.

## WP-0c interaction (lead request)

WP-0c is merged on this branch through `mig/integration`, and its three contract changes are re-recorded:

- `field.info.unknown_id`: 404 (was 200 with count 0 on this stack; a 500 against a datasource with rows).
- `field.info.over_cap`: 400 for 21 ids (was 200).
- `auth.timeout`: a timed-out session's response now clears `accessKey`, `refresh_token_cookie`, `csrf_access_token` and `csrf_refresh_token` (was no Set-Cookie).
- `GET /api/dimension/<name>/<value>` is deleted by WP-0c; no call exists in `web/client` or `web/python_client`.
- For WP-5d (SEC-5): `auth.login.cookie` records `accessKey; session; httponly; path=/`, so the cookie is set without `Secure` and without `SameSite`.

## Findings

Found while recording. None is fixed here (QA never edits production code); each is a request above. Recordings encode today's behaviour, so the WP that fixes a finding updates its recording and says why in its log.

- **F1. Raw-data export sends a payload the server rejects.** `ShareQueryModal` calls `TableQueryResultState.runRawQuery`, which posts `QuerySelections.serializeForDisaggregatedQuery()` (`web/client/models/core/wip/QuerySelections/index.js:147-180`) to `POST /api2/query/table/disaggregated`. That payload carries `includeNull`, `includeTotal` and `name`, and the server's `QUERY_REQUEST` schema forbids extra keys.
  - Repro: stack up, then `record.py --only 'query.table.disaggregated.client_payload'`.
  - Expected: 200 with rows. Actual: 400 `Additional properties are not allowed ('includeNull', 'includeTotal', 'name' were unexpected)`. `QueryInterface.js:69` swallows the error, so the user sees an empty export.
  - Evidence: `tests/contract/recordings/query.table.disaggregated.client_payload.json`.
- **F2. Eight client endpoints have no server route.** `GET /api2/query/fields`, `/categories`, `/datasets`, `/dimensions`, `/dimensions/authorized`, `/field_metadata` (`web/client/services/wip/*Service.js`), `GET /api2/raw_pipeline_entity/search_metadata` (`services/EntityMatchingApp/EntityDimensionValueService.js:59`) and `GET /api2/alert_notifications/all_filtered` (`services/AlertsService.js:136`) all return 404. Evidence: the seven `*.missing_route.json` recordings and `alert_notification.all_filtered.json`. `patchLegacyServices()` swaps the field, dimension and field-metadata services onto GraphQL in the apps that call it (AQT, data quality, data digest, data upload). Anywhere else, and for categories, datasets and entity search, the REST call 404s.
- **F3. A fresh web image on `main` cannot hash or verify passwords.** Fixed by WP-0b (`bcrypt==4.0.1` in `requirements.txt`). Before that, `bcrypt` was unpinned, and bcrypt 5 with passlib 1.7.4 raised `ValueError: password cannot be longer than 72 bytes` on every hash and verify (INV-1). The stack's shim image was deleted in round 4.
- **F5. Validating a non-zip self-serve upload returns 500, not 400.** `contains_valid_zipped_files` (`web/server/routes/views/validate_data_catalog.py:376`) raises on a file that is not a zip. Evidence: `recordings/self_serve.validate.rejects_non_zip.json`.
- **F6. An unconfigured stack mails through Mailgun.** `SMTP_CONFIG` defaults `EMAIL_HOST` to `smtp.mailgun.org` (`web/server/configuration/flask.py`); without mail settings every email-sending endpoint stalls about 5 s connecting out.
- **F7. `web/python_client` never logs in.** It posts `{username, password}` to `/authentication/login` (`web/python_client/core.py:29-46`), which has no route. The answer is 405, and the loop only moves on to its second URL, `/api/login`, after a 404, so that fallback is unreachable (and `/api/login` does not exist either). The client then sends `X-Username`/`X-Password` on every request; the bearer-token branch is never reached. Evidence: `recordings/client.login_attempt.json`; the `client*` sessions record that header mechanism.
- **F8. `PATCH /api2/user/<id>` answers 200 with an all-null user.** The handler returns the function `update_user_groups` (`web/server/api/user_api_models.py:150`). Evidence: `recordings/user.update.json`.
- **F9. `GET /api2/dashboard/<id>?legacy=1` returns 500** for a dashboard with no legacy specification: `_get_specification_version` calls `.get` on `None` (`web/server/routes/views/dashboard.py:50`). Evidence: `recordings/dashboard.get.legacy.json`.
- **F10. The role-map endpoints break and destroy data.** `PATCH /api2/user/<id>/roles` and `PATCH /api2/group/<id>/roles`:
  - with any non-empty map raise `TypeError: 'resource_id' is an invalid keyword argument for UserRoles` (`GroupRoles`) in `add_user_role`/`add_group_role` (`web/server/routes/views/users.py:187`, `groups.py:94`), so they 500;
  - start by `session.delete(role)` over `user.roles`/`group.roles`, which are `Role` rows through a secondary table, so clearing a holder's roles deletes those roles for everyone. Reproduced: on a fresh stack, with `contract_role` attached to `contract-group`, `PATCH /api2/group/<id>/roles {}` removed `contract_role` from `GET /api2/role` (`/tmp/wp2c_rolewatch.py`). The cases therefore delete the role first and clear an empty group. Decision 0004 puts this in WP-0h.
  - `web/python_client` (`directory_service/service.py:63, 124`) and the unused `DirectoryService.updateUserRoles`/`updateGroupRoles` send this shape. Evidence: `recordings/{user,group}.update_roles.{clear,assign}.json`.
- **F11. `/api2/storage/retrieve`**: an unknown slug is a 500 (the handler dereferences the missing dashboard). A cache miss renders through Urlbox with a freshly minted render-bot `accessKey` JWT in the request URL (`web/server/routes/views/page_renderer.py`, `grid_dashboard_urlbox_renderer`), so a token for a site-admin account reaches a third party; when Urlbox is unreachable the request 500s and leaves a PENDING marker that makes every later read for that slug sleep for 10 minutes (`web/server/redis/thumbnail_storage_service.py:25-39`). Decision 0004 puts the route in WP-0i (SEC-7, SEC-10). Evidence: `recordings/storage.retrieve.unknown_slug.json`; the miss was observed and is not recorded.

- **F12. A generated API token is not stored.** Fixed by backend at `48ff9a3`: the route now stores the token (see "Backend support"). The text below describes the behaviour before the fix. `POST /api2/user/<id>/generate_api_token` returns `APIToken.generate_token(user)` (`models/alchemy/api_token/model.py:40`). That builds the row and signs the JWT but never adds the row to the session. Authentication looks the token id up in the table (`check_token_validity`, `web/server/security/signal_handlers.py:278`). So the token only works after the admin app saves the user with it in `apiTokens` (`UserViewModal/index.jsx:321`). If the admin closes the modal without saving, or a script calls the route directly, the token never authenticates.
  - Repro: stack up, run `user.generate_api_token`, then `GET /api2/user/<id>`.
  - Expected: the new token in `apiTokens`. Actual: `apiTokens` is `[]` until `user.update.persist_api_token` PATCHes it in.
  - Evidence: `recordings/user.generate_api_token.json`, `recordings/user.update.persist_api_token.json`, `recordings/user.get.with_api_token.json`.
- **F13. Importing a self-serve export deleted rows it does not import.** Fixed by core at `d016bce` (merged here at `84b8cf7`). The text below the code path describes the behaviour before the fix.
  - Code path: `POST /api/import_self_serve` (`web/server/routes/api.py:177`) runs `scripts/data_catalog/import_db_tables.py` in a subprocess (`api.py:185`). That script passes `DATA_CATALOG_TABLE_NAMES` (`import_db_tables.py:27`, the list and order of tables the import replaces) to `import_data_into_table` (`db/postgres/utils.py`). Before the fix, that function ran `TRUNCATE TABLE ... RESTART IDENTITY CASCADE` before each `COPY`.
  - `CASCADE` also emptied every table that has a foreign key into the listed tables but is not in the export:
    - `unpublished_field_category_mapping`, `unpublished_field_pipeline_datasource_mapping` and `unpublished_field_dimension_mapping`;
    - `geo_dimension_metadata`, `hierarchical_dimension_metadata` and `non_hierarchical_dimension`;
    - `source_config`.

    Re-importing an unchanged export therefore lost Field Setup mappings and dimension metadata. The import also ran in autocommit, so a failed import left the earlier tables already replaced.
  - Repro: stack up (the seed gives the unpublished field one category mapping and one datasource mapping), run `self_serve.export`, then `self_serve.import.exported_zip`, then count the rows in the two mapping tables.
  - Expected: 1 and 1. Actual before the fix: 0 and 0, while `pipeline_datasource` and `category` kept their rows. After the fix both mappings survive: `BatchPublishModalContentsQuery`, recorded after the import case, carries them.
  - The fix, in one transaction (details under "F13: core review and fix"):
    1. Check that the archive has every listed table, then COPY each into a staging table.
    2. Empty the leaf tables, the ones no foreign key references (the mapping tables, `dataprep_job`, `data_upload_file_summary`).
    3. Upsert the referenced tables on their primary keys, parents first.
    4. Delete only the rows the export lacks, children first. A cascade now reaches only rows that referenced a row the export removed.
    5. Reload the leaves, then check that each imported table holds exactly the archive's row count.
    6. Advance the id sequences after every check has passed, never below the value already used.

    There is no `TRUNCATE ... CASCADE`. Dependent rows survive while the export still carries the row they reference.
  - INV-2 before and after, and the performance table (old against new at 50k and 100k fields), are under "F13: core review and fix". In short: a failed or inconsistent import now changes nothing, readers see the old catalogue until commit, and the import is slower but stays inside the route's 120 s timeout at both sizes.
  - Ruled out: `DELETE` without `CASCADE`. The dependent foreign keys are themselves `ON DELETE CASCADE`, so deleting the parents still empties `source_config` and the datasource mapping (reviewer, verified on a stack). A plain `TRUNCATE` without `CASCADE` errors on those foreign keys. Deleting absent rows before the upsert, as backend's first patch did, cascades into rows the export carries (core).
  - Evidence: `tests/db/test_import_data_into_table.py` (9 passed; 6 failed with the pre-fix code); `recordings/graphql.BatchPublishModalContentsQuery.json`, which records the publishable field after the import case; the round-3 reproduction (`/tmp/wp2c_f13.py`).
  - Follow-ups (core's export transaction and COPY column order, backend's 120 s timeout) are under Requests.

## Backend support: F12 and F13 (backend-2c)

Branch `mig/WP-2c-api-contract-recordings-backend`, from `00e5047`.

### F13: reproduction and proposed fix

- **Failing tests** (shared paths): `tests/db/test_import_data_into_table.py`, run against a throwaway Postgres from `tests/throwaway_postgres.py`. That is the stack's pinned `postgres:15.2-alpine` image on a random loopback port, or `HARMONY_TEST_POSTGRES_URL`; the tests skip when neither is available. The tests build the catalogue schema from `models/alchemy/{query,data_upload}`, seed every imported table plus one row in each of the 7 dependent tables, then call `export_tables_to_zip` and `import_data_into_table` with the table lists the route's scripts use. Run: `ZEN_ENV=harmony_demo uv run pytest tests/db -q`.
  1. `test_reimporting_an_unchanged_export_keeps_rows_in_tables_it_does_not_carry`. On `00e5047` it fails: all 7 dependent tables come back empty.
  2. `test_an_import_makes_the_catalogue_tables_match_the_export`. A renamed category is restored, and a category added after the export is removed together with its dependent mapping (ON DELETE CASCADE), while the mapping of a category the export carries survives. Fails on `00e5047`.
  3. `test_mapping_rows_whose_ids_differ_from_the_export_are_replaced`. Mapping ids drifted between instances, so each id holds the other row's `(dimension_id, category_id)` pair. Passes on `00e5047`; it guards the fix against unique-constraint collisions.
  4. `test_a_failed_import_changes_nothing`. The export's `category` lacks a row that `field_category_mapping` references. On `00e5047` the import raises after it has already replaced earlier tables, because it ran in autocommit.
- **Result on `00e5047`**: 3 failed, 1 passed.
- **Proposed fix** (core owns `db/postgres/utils.py`, routed through the lead): `WP-2c-evidence/F13-db-postgres-utils.patch`. With the patch loaded through a pytest plugin and no edit to the repo: 4 passed. A mutation that drops the leaf-table rule turns test 3 red. What the patch does:
  1. Runs the import in one transaction.
  2. COPYs each table into a temporary staging table.
  3. Children first, deletes the rows whose primary key the export does not carry. A table that no foreign key references is emptied instead.
  4. Parents first, runs `INSERT ... SELECT ... ON CONFLICT (pk) DO UPDATE`.
  5. Drops `TRUNCATE ... CASCADE`.
- **Behaviour before and after** (INV-2-relevant; for the human acceptance list):
  - Before: an import emptied the 7 dependent tables (`unpublished_field_{category,pipeline_datasource,dimension}_mapping`, `geo_dimension_metadata`, `hierarchical_dimension_metadata`, `non_hierarchical_dimension`, `source_config`), and a failed import left some catalogue tables replaced.
  - After: the imported tables hold exactly the export's rows, as before. Dependent rows survive while the export carries the row they reference, and are deleted with it otherwise. A failed import changes nothing.
  - Rows are matched on primary keys. The catalogue's parents use string ids, which are stable across instances. `source_config` references `self_serve_source` by serial id, so on a cross-instance import a surviving `source_config` row follows whichever source holds that id in the export.
  - Known limit: a referenced table whose secondary unique value moves between two surviving rows (`dataprep_flow.recipe_id`) makes the import fail and roll back rather than succeed.

### F13: core review and fix (core, `mig/WP-2c-api-contract-recordings-core`)

Core reviewed the patch as owner and did not apply it as is. Two of its steps lose or corrupt data. The fix at `d016bce` keeps its staging, upsert and leaf-table ideas and changes the order.

- **Defect 1 in the patch: deleting before upserting cascades into rows the export carries.** The patch deletes absent parent rows before upserting. At that point the target's rows still hold their old foreign keys. Say the export moves `cat_a` under `cat_new` and drops `cat_old`, while the target still has `cat_a` under `cat_old`. Deleting `cat_old` then cascades through `category.parent_id` to `cat_a`, and from there to `cat_a`'s unpublished-field mapping. The upsert puts `cat_a` back, but the mapping is gone. The same thing happens across tables when a `self_serve_source` row the export carries points at a `pipeline_datasource` the export drops: its `source_config` is lost. New test `test_a_dependent_of_a_row_the_export_carries_survives_its_old_parents_removal` fails with the patch (`unpublished_field_category_mapping` becomes `[]`).
- **Defect 2 in the patch: a failed import can rewind id sequences.** The patch runs `setval` per table during the upserts. `setval` is not transactional, so a later failure rolls back the rows but not the sequence. The app's next insert then reuses a live id. New test `test_a_failed_import_leaves_id_sequences_ahead_of_the_rows` fails with the patch (`UniqueViolation ... Key (id)=(2) already exists`).
- **Order in `d016bce`**, all in one transaction:
  1. Check that the archive has every listed table, else `ImportTableDataError` before anything changes.
  2. COPY each table into a `LIKE` staging table and `ANALYZE` it.
  3. Empty the leaf tables. A leaf is a table that no foreign key references; the code reads this from `pg_constraint`.
  4. Upsert the referenced tables, parents first (`INSERT ... SELECT ... ON CONFLICT (pk) DO UPDATE`). Every row the export carries now has its new foreign keys.
  5. Delete the absent rows of the referenced tables, children first. A cascade reaches only rows that referenced a row the export removed.
  6. Insert the leaves. A leaf row that references a parent the export dropped fails here with an FK `IntegrityError`, as it did before.
  7. Check that each imported table holds exactly as many rows as its staging table. If an inconsistent archive drops a parent of a row it carries, step 5 cascades into an exported row; the check turns that into `ImportTableDataError` and a rollback.
  8. Advance the id sequences, after every check has passed. The new value is `GREATEST(last value used, max(id)) + 1`, so a sequence never moves back. A rollback after this point, for example a failure at COMMIT, leaves sequences ahead of the rows, never behind.
- **Identity sequences.** RESTART IDENTITY is gone and is not needed: step 8 moves each sequence past every id in its table. The non-lowering rule is a small change from before. The old code set the sequence to the export's `max(id) + 1`; now it never goes below what the target has already handed out. Ids are internal, so nothing user-visible changes. The dependent tables are not written, so their sequences are untouched.
- **FK ordering.** Every foreign key into an imported table was listed from the SQLAlchemy metadata of all models. They all come from the imported tables themselves or from the 7 dependent tables, and all are `ON DELETE CASCADE`. The reviewer confirmed the cascades on a stack. Self-references (`category.parent_id`, `dimension_category.parent_id`, `field.copied_from_field_id`) are safe in one `INSERT ... SELECT`, because Postgres checks non-deferrable FKs at the end of each statement. The upsert relies on the caller's order (each table after the tables it references). `DATA_CATALOG_TABLE_NAMES` in `scripts/data_catalog/import_db_tables.py:27` already satisfies it: `category, dimension, dimension_category, field, pipeline_datasource, dataprep_flow, self_serve_source` among the referenced tables. That script needs no change.
- **Why leaf tables are emptied.** Leaves are the four mapping tables, `dataprep_job` and `data_upload_file_summary`. They have serial ids that drift between instances, plus a unique pair, for example `(field_id, category_id)`. Upserting on `id` would collide with the pair held by another id (test 3). Nothing references a leaf, so emptying it can cascade nowhere and loses no identity worth keeping. If a future migration adds an FK into a mapping table, that table moves to the upsert path by itself. Mutation check: upserting the leaves instead of emptying them turns test 3 red.
- **Export carries a table absent from the target, or lacks a listed table.** Only the listed tables are read, and extra archive members are ignored. A listed table missing from the archive raises `ImportTableDataError` naming it, before anything is written (`test_an_archive_missing_a_table_changes_nothing`). A listed table missing from the target database makes `CREATE TEMPORARY TABLE ... (LIKE ...)` raise `UndefinedTable` during staging, and the transaction rolls back. Before the fix, the same case failed after the earlier tables were already replaced.
- **Performance** (scratch `postgres:15.2-alpine`, synthetic catalogue, `WP-2c-evidence/F13-perf.py`; old is `d23076f:db/postgres/utils.py`, before the fix):

  | Catalogue | Old | New |
  |---|---|---|
  | 50k fields, 500k dimension mappings, 50k category and datasource mappings, 10k unpublished mappings | 14.1-16.8 s, empties the dependent tables | 17.9-32.7 s, dependents kept |
  | 100k fields, 1M dimension mappings | 36.5 s, empties the dependent tables | 41.0-58.0 s, dependents kept |

  The time goes to inserting `field_dimension_mapping`: FK and unique checks on every row, as with the old COPY, plus index entries left by the DELETE. `TRUNCATE` (without CASCADE) on the leaves would be faster. Inside the transaction, though, it holds an ACCESS EXCLUSIVE lock until commit, which blocks every web request that reads field mappings for the length of the import. With DELETE, readers keep the old catalogue until commit. The old code was worse here: it showed readers empty tables between each TRUNCATE and its COPY. Both sizes are well above a current deployment's catalogue and stay inside the route's 120 s subprocess timeout.
- **Tests** (`tests/db/test_import_data_into_table.py`, `ZEN_ENV=harmony_demo uv run pytest tests/db -q`): 9 passed at `d016bce` and on the merge with backend's `8804af2`. The 5 new cases:
  - the reparent case (defect 1);
  - a failed import leaves sequences ahead (defect 2);
  - a failure at COMMIT, injected with a deferred constraint trigger, leaves sequences ahead;
  - an archive that drops the parent of a row it carries changes nothing;
  - an archive missing a table changes nothing.
- **Mutations** (`WP-2c-evidence/F13-mutate.py`), each killed:
  - drop the count check: 1 red;
  - delete before upsert: 2 red;
  - let sequences move back: 1 red;
  - upsert the leaves: 2 red.
- **Other checks:** ruff clean on both changed files, and the 4 pre-existing `List`/`Optional` findings in `db/postgres/utils.py` are fixed. The module is not reformatted, because it predates ruff format. mypy (`uv run --with mypy --with sqlalchemy-stubs --with types-psycopg2 mypy --follow-imports=silent`) is clean on both files. Golden: 269 passed. `tests/authz` is not on this branch.
- **Behaviour before and after** (INV-2; for the human acceptance list). This supersedes the patch's list above where they differ:
  - Before: an import emptied the 7 dependent tables. A failed import, or one cut off part-way, left some catalogue tables replaced. Web readers saw empty catalogue tables while the import ran.
  - After: the imported tables hold exactly the archive's rows, as before. A dependent row survives while the archive carries the row it references, even if that row's own parent changed. It goes, by ON DELETE CASCADE, only with a row the archive removes. A failed import changes nothing, and readers see the old catalogue until commit. Archives that are inconsistent or missing a table are refused. Id sequences never move back.
  - Unchanged known limits: rows are matched on primary keys, so on a cross-instance import a surviving `source_config` row follows whichever `self_serve_source` holds its serial id. A `dataprep_flow.recipe_id` collision between surviving rows rolls the import back.
- **Follow-ups, not done here (core unless noted):**
  - `export_tables_to_zip` copies each table in its own autocommit transaction, so an export taken during edits can be inconsistent. The import now refuses such an archive. Exporting in one `REPEATABLE READ READ ONLY` transaction would stop producing them.
  - COPY maps CSV columns by position. A target whose column order differs from the source (a schema built by `create_all` against one built by Alembic) would misload. This predates F13.
  - Backend: when the import outlives the 120 s timeout, `communicate` raises, the `with Popen` block waits for the child anyway, and the route can return an error for an import that then commits.

### F12: fix

- **Decision**: the route stores the token (`web/server/routes/views/users.py` `issue_api_token`, called by `create_api_token_for_user`). That is the smallest fix that makes the route's answer true. The admin app's later save stays safe: `update_user_api_tokens` inserts with `ON CONFLICT DO NOTHING`, so the same token is neither duplicated nor rejected. `models/alchemy/api_token/model.py` (core) is unchanged. The route sets `user_id` itself because `generate_token` attaches the user through a view-only relationship.
- **Test first**: `tests/web/test_api_token_issue.py`, on the throwaway Postgres.
  - `test_a_generated_api_token_authenticates_without_saving_the_user`: the token's claim id is in the table, belongs to the user and passes `check_token_validity`. With the helper returning the unsaved token, as the route did, it failed: `check_token_validity(...)` was False.
  - `test_the_admin_apps_later_save_keeps_the_stored_token`: after the admin app's save there is one stored copy and it still authenticates. A later save with `is_revoked` makes it stop authenticating.
- **Live** (fresh stack at `48ff9a3`, `/tmp/f12_live.py`, a dedicated user deleted afterwards):
  - `generate_api_token` returned 200 with the same keys.
  - The token was listed on the user without a PATCH.
  - `GET /api2/user/<id>` with `Authorization: Bearer <token>` returned 200. A malformed bearer returned 422.
  - The admin app's PATCH with the same token returned 200 and left one copy, still valid.
  - A PATCH with `isRevoked: true` returned 200, and the bearer then returned 401.
- **Contract**: no recording changes. Replay on a fresh stack passed 231 of 231, twice. `user.generate_api_token` keeps its schema: `isRevoked` was boolean already, and `created` and `revoked` are dates. `user.get.with_api_token` reads the same item. For the owner (qa), two case notes in `cases/20-directory.json` are now stale:
  - `user.generate_api_token` says it returns the token "without storing it";
  - `user.update.persist_api_token` says generate_api_token "stores nothing".

  Suggested wording: the route stores the token, and the PATCH is the admin app's save, which keeps it (F12, fixed by backend at `48ff9a3`).
- **Behaviour before and after** (authentication; for the human acceptance list): a generated token now works at once, rather than only after the admin saves the user.
  - If the admin closes the modal without saving, the token stays active. It is listed under the user's API tokens and can be revoked there.
  - Who can obtain a working token does not widen. The route still requires `change_password` on the user, which the code already treats as equivalent to account access (`user_api_models.py:159-163`). Before, anyone holding that permission could also set the user's password.
  - Follow-up for frontend-design (not blocking): the copy toast in `web/client/components/AdminApp/UsersTab/UserViewModal/APITokensTab.jsx` says "Do not forget to save changes before using it!". That is no longer true for new tokens. Revocation still needs Save.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-04 | 2026-10-04 qa-2c-review round 3 at 00e5047 (e8b5812 differs only in the WP file): dry run 231 cases 0 problems, offline 51, schema tests under three hypothesis seeds, recording on two fresh stacks byte-identical to the committed set and to each other, replay 282 twice on a recorded and on a never-recorded stack, 13 of the 14 empty Relay recordings now carry items and all 51 operations are covered, F13 reproduced (TRUNCATE RESTART IDENTITY CASCADE empties both mapping tables), apiTokens recorded with the token typed null, four deliberate breaks fail by name without leaking the live email or the secret, isolation and secrets-file checks hold, no external host resolves from the stack, stacks cleaned up. Low: 80-graphql.json:215 and WP-2c.md:105 claim UnpublishedFieldTableRowsQuery pins the BatchPublish node shape but only scalars are pinned and the datasource-mapping item shape is pinned nowhere, correct R2 and Limits or record before the import case; info: persist_api_token sends created and revoked as null where the client sends date strings. |
| reviewer | changes-requested | 2026-10-04 | 2026-10-04 rev-2c round 3 at e8b5812: every round-2 finding closed and checked (apiTokens pinned via PATCH, seed_catalog.py transactional and loud on failure, percent-wrapped search text correct, replay reports pin diffs without values, inventory and keys fixed); offline 51, dry run 231/0, replay 231 twice on a fresh stack and 231 on a merge with integration 215f03b; QA-2, INV-1, INV-6 met; F12 precise (route returns an unsaved APIToken, viewonly relationship; storing in the route is safe because update_user_api_tokens inserts on_conflict_do_nothing). Short round: F13's first remedy (DELETE without CASCADE in one transaction) does not work because the dependent FKs are ON DELETE CASCADE (verified: DELETE still empties source_config and the datasource mapping; plain TRUNCATE errors), replace with TRUNCATE without CASCADE over the full table set plus adding the dependents to the export, or upsert then delete only absent rows, and name the real code path (api.py:184 runs scripts/data_catalog/import_db_tables.py whose table list and order is what changes); merge integration, delete the shim Dockerfile and tag the web-server image directly now WP-0b's bcrypt pin is in the base, close the misaddressed infra request and mark F3 fixed; Limits incomplete (fieldPipelineDatasourceMappings empty in four field queries, unpublished category mappings empty in two) and the BatchPublish inventory row overstates coverage. Nits: the v2 thumbnail key note must say seed_cache.py runs before any case so a non-HTTP step or a predicted resource id is needed; runner.py prints the observed value in the int() ValueError; seed_catalog.py:3 docstring wrong about useSelfServeMutation; fold the empty-connection scan into test_catalogue. |
| security | n/a | |
