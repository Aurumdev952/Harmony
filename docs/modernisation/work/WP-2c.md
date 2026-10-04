---
wp: "2c"
title: "API contract recordings"
status: review
owner_role: "qa"
instances:
  - name: "qa-3"
    files: ["tests/contract/**", "docs/modernisation/work/WP-2c.md"]
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

Files: `tests/contract/**`, this file and QA memory. No production code changes.

## Contract changes

None. This WP records the existing Flask contract; it changes no producer.

## Requests

None of these block WP-2c; each comes from a finding below or from the review.

- [ ] infra (WP-2f): add pinned `hypothesis` and `jsonschema` (and `requests`, which the replay uses) to the `dev` group, register the `stack` marker in `[tool.pytest.ini_options]`, add `tests/contract` to `testpaths`, and run `pytest tests/contract -m "not stack"` on every PR and `-m stack` in the job that brings the stack up. Until then `tests/contract/conftest.py` registers the marker itself and the commands in `INVENTORY.md` use `uv run --with`.
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
- [ ] infra: WP-0b's `requirements.txt` pin of `bcrypt==4.0.1` fixes F3. When it lands, delete `tests/contract/stack/Dockerfile` and build `docker/web/Dockerfile_web-server` directly.
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
- [x] backend or QA (WP-0a): record the 11 deferred Relay mutations. Done in unit 7: `stack/seed_catalog.py` seeds the rows they edit, and all 51 Relay operations are recorded. WP-0a's `replay_relay_operations.py` still carries its own variables. Whichever WP touches Relay next should make one of the two the source.
- [ ] backend: `POST /api2/user/<id>/generate_api_token` returns a token it does not store (F12). Either store it there, or document that the caller must save the user. A script that calls the route alone gets a token that never authenticates.
- [ ] backend: `POST /api/import_self_serve` truncates each data-catalog table with `CASCADE`, so it deletes rows in tables it does not import (F13). Delete and reload without `CASCADE` inside one transaction, or export and import the dependent tables too.

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
| R2 | Nine Relay queries recorded empty connections (reviewer) | `stack/seed_catalog.py` (run by `init.sh`) seeds a dimension, two pipeline datasources, an unpublished field with mappings, a Dataprep flow and a self-serve source. The unpublished-field table queries now send `%%`, as the client does. The `ALL_SOURCES` pipeline-run seed carries `next_run`. At `fa72fe0`, 14 Relay recordings had an empty top-level connection; 13 now record items. The 14th, `BatchPublishModalContentsQuery`, stays empty because `self_serve.import.exported_zip` deletes the seeded datasource mapping (F13). `UnpublishedFieldTableRowsQuery` pins the same node shape. The 11 deferred mutations are recorded too, so 51 of 51 Relay operations are covered. | `/tmp/wp2c_edges.py` over the recordings; `INVENTORY.md` Relay table |
| R3 | A changed pinned value raised instead of a diff (reviewer) | During replay, `observe` never raises: it replaces an unsafe value with a marker. `record.py` passes `recording=True`, which still refuses unsafe pins. New test: `test_a_replay_reports_an_unsafe_pinned_value_without_echoing_it`. | broken-recording run below |
| R4 | Stale `POST /graphql` row (reviewer) | Row deleted. WP-0d removed `r/graphql_api.py` and `zen_environment.js`. | `INVENTORY.md` |
| R5 | `data_upload.sources_date_ranges` and `resource.roles*` keyed by data (reviewer, QA) | `maps: ["$"]` and `maps: ["$.groupRoles", "$.userRoles"]`. | the three recordings |
| R6 | F10/F11 numbering (reviewer) | Both case notes say F10. | `cases/20-directory.json`, `cases/95-cleanup.json` |
| R7 | Non-blocking (reviewer) | `auth.login.cookie.remember_me` records `accessKey` as persistent. The Linux-only note and the phase-5 section are in `INVENTORY.md`. The `date` row WP-2f asked for is in `test_schema.py`. | `INVENTORY.md`, `recordings/auth.login.cookie.remember_me.json` |

## Evidence

Round 3 was re-run in full on 2026-10-04 by qa-3 at `dc935f5` (branch `mig/WP-2c-api-contract-recordings`, on top of `fa72fe0`), with Docker 29, Compose v5 and uv 0.12. Live runs used a disposable stack with `CONTRACT_PROJECT=wp2c-r3 CONTRACT_WEB_PORT=58761` and `eval "$(tests/contract/stack/stack.sh env)"`. The image was rebuilt after the host reboot (`harmony-contract-web:2eea3033e2a4`).

- **Static**: `ruff format --line-length 88 --check tests/contract` reports 17 files already formatted; `ruff check --line-length 88` reports all checks passed.
- **Dry run**: `python -m tests.contract.record --dry-run` reports `231 cases, 0 problems`.
- **Offline suite**: `pytest tests/contract -m "not stack"` reports `51 passed, 231 deselected`.
- **Properties**: `test_schema.py` passes 22 tests under `--hypothesis-seed` 1, 2 and 3.
- **Recording is reproducible**: all 231 cases were recorded on a fresh stack. Then `stack.sh down`, `stack.sh up`, and a second recording. Neither run had an error or skip, and `diff -r` between the two sets of recordings is empty.
  - Status mix: 181x 200, 18x 204, 1x 302, 11x 400, 4x 401, 10x 404, 1x 405, 5x 500.
  - The 500s are F5, F9, F10 (two) and F11.
- **Replay, same stack**: `pytest tests/contract` (offline plus `stack`) reports `282 passed`, twice back to back.
- **Replay, new stack**: after `stack.sh down` and `stack.sh up`, the same command reports `282 passed`, twice.
- **Broken recordings turn red**: two recordings were broken on purpose.
  - Changes: `apiTokens[].isRevoked` set to `string` in `recordings/user.get.with_api_token.json`; the pinned `/success` set to `false` in `recordings/self_serve.import.exported_zip.json`.
  - Result: `pytest -m stack` reports `2 failed, 229 passed`, with the diffs `$.apiTokens[].isRevoked: type ['string'] != ['boolean']` and `pinned /success: False != True`.
  - Both files were restored, and `diff -r` against the recorded set was empty again.
- **F13 reproduced** (`/tmp/wp2c_f13.py`): the seeded datasource mapping was re-inserted on the stack. Then `self_serve.export`, `self_serve.import.exported_zip` and `configuration.reset.after_import` ran through the runner. `unpublished_field_category_mapping` went from 1 row to 0 and `unpublished_field_pipeline_datasource_mapping` from 1 to 0. `pipeline_datasource` and `category` kept their rows.
- **Isolation**:
  - Only `forward` publishes a port (`127.0.0.1:58761`).
  - From the web container, `smtp.mailgun.org` and `api.urlbox.io` do not resolve, and `1.1.1.1:443` is unreachable.
  - The secrets file was mode 600 and owned by the user. `stack.sh down` removed it and left no `wp2c-r3` container.
- **No secrets or PII in fixtures** (INV-6): `test_recordings_hold_no_values_that_look_like_secrets_or_pii` scans all 231 recordings. The stored API token's `token` field is recorded as `null`. As in round 2, 27 values are pinned across 23 recordings.

Limits:
- 17 of 145 routes are deferred, each with its reason in `INVENTORY.md`: object storage, Dataprep, Urlbox rendering, `hierarchy` under the mock Druid, dead client code, and a static GeoJSON asset. No Relay operation is deferred.
- Some lists are still empty in every recording:
  - unpublished-field datasource mappings and `BatchPublishModalContentsQuery`'s connection (F13);
  - nested lists that no seed fills: dimension mappings on fields, Dataprep jobs, file summaries and category children.

  `/tmp/wp2c_empty.py` lists them.
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
- **F3. A fresh web image on `main` cannot hash or verify passwords.** `bcrypt` is unpinned; bcrypt 5 with passlib 1.7.4 raises `ValueError: password cannot be longer than 72 bytes` on every hash and verify (INV-1). WP-0b pins it. Workaround in the stack only: `tests/contract/stack/Dockerfile`.
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

- **F12. A generated API token is not stored.** `POST /api2/user/<id>/generate_api_token` returns `APIToken.generate_token(user)` (`models/alchemy/api_token/model.py:40`). That builds the row and signs the JWT but never adds the row to the session. Authentication looks the token id up in the table (`check_token_validity`, `web/server/security/signal_handlers.py:278`). So the token only works after the admin app saves the user with it in `apiTokens` (`UserViewModal/index.jsx:321`). If the admin closes the modal without saving, or a script calls the route directly, the token never authenticates.
  - Repro: stack up, run `user.generate_api_token`, then `GET /api2/user/<id>`.
  - Expected: the new token in `apiTokens`. Actual: `apiTokens` is `[]` until `user.update.persist_api_token` PATCHes it in.
  - Evidence: `recordings/user.generate_api_token.json`, `recordings/user.update.persist_api_token.json`, `recordings/user.get.with_api_token.json`.
- **F13. Importing a self-serve export deletes rows it does not import.** Before each `COPY`, `import_data_into_table` (`db/postgres/utils.py:197`) runs `TRUNCATE TABLE ... RESTART IDENTITY CASCADE` on the data-catalog table. `CASCADE` also empties every table that has a foreign key into those tables but is not in the export:
  - `unpublished_field_category_mapping`, `unpublished_field_pipeline_datasource_mapping` and `unpublished_field_dimension_mapping`;
  - `geo_dimension_metadata`, `hierarchical_dimension_metadata` and `non_hierarchical_dimension`;
  - `source_config`.

  Re-importing an unchanged export therefore loses Field Setup mappings and dimension metadata.
  - Repro: stack up (the seed gives the unpublished field one category mapping and one datasource mapping), run `self_serve.export`, then `self_serve.import.exported_zip`, then count the rows in the two mapping tables.
  - Expected: 1 and 1. Actual: 0 and 0, while `pipeline_datasource` and `category` keep their rows.
  - Evidence: the F13 line under Evidence; `recordings/graphql.BatchPublishModalContentsQuery.json` (no publishable field).

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | changes-requested | 2026-10-06 qa-2c-review at af61253: every round-1 check and finding passes (isolation, internal network, secrets file mode, image hash tags, 265 replay on two fresh stacks, byte-identical re-recording, three broken recordings red by name, no PII). Two small fixes: apiTokens is empty in every recording because APIToken.generate_token never saves the token (log as F12 to backend; correct unit 5; add a case note or seed a token); resource.roles recordings use a group name as a schema key (declare maps $.groupRoles on both cases and re-record). |
| reviewer | changes-requested | 2026-10-06 rev-2c at af61253: 13 of 14 findings closed; overlays proven against WP-0b and current integration (216 and 265 passed). Short round: apiTokens still unpinned (PATCH the user with the token before the GET, or correct the claim); nine Relay operations marked recorded pin only empty connections (seed dimension, unpublished_field, pipeline_datasource, dataprep_flow rows or mark recorded-empty); a changed pinned value raises instead of a diff line (refuse only when recording); stale POST /graphql inventory row after WP-0d; data_upload.sources_date_ranges needs maps $; F10/F11 numbering in two case notes. Non-blocking: remember-me login case; Linux-only stack note; phase-5 notes into INVENTORY; WP-2f's date-tag test row. |
| security | n/a | |
