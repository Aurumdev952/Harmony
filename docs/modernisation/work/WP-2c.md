---
wp: "2c"
title: "API contract recordings"
status: review
owner_role: "qa"
instances:
  - name: "qa-2"
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
- [ ] backend or QA (WP-0a): record the 11 deferred Relay mutations from the variables in WP-0a's `scripts/db/hasura/replay_relay_operations.py` once a fixture creates unpublished fields and self-serve sources; one tool should own those variables, not two.

## Log

- 2026-10-04 qa-2 unit 1: shape-only JSON Schema infer/merge/diff with property tests; check: `pytest tests/contract/test_schema.py` 18 passed (seeds 1-3 too); mutation run killed 6 of 6 mutants after adding the required-drift example.
- 2026-10-04 qa-2 unit 2: disposable stack in `tests/contract/stack/`; check: `stack.sh up` from nothing reaches `web is up`, login returns 200, only the web port published on loopback.
- 2026-10-04 qa-2 unit 3: recorder, runner, replay, dry-run; check: `pytest tests/contract/test_cases.py` green, dry-run lists every case without network, record-then-replay round trip green.
- 2026-10-04 qa-2 unit 4: inventory, cases, recordings, catalogue checks; check: offline suite green; replay green twice on the recording stack and on a second fresh stack; a deliberately broken recording turns replay red.
- 2026-10-04 qa-2 unit 5 (lead request from WP-0c): `/api/field` edge cases and the cookies observation; check: unit tests green, fresh-stack record and replay.
- 2026-10-04 qa-2: status review; QA and reviewer verdicts changes-requested.
- 2026-10-05 qa-2 unit 6: review fixes (see Plan 6 and "Review fixes" below); merged `mig/integration` (WP-0a, WP-0c, decision 0003/0004; `.playwright-mcp` gone, `git ls-files .playwright-mcp` empty); re-recorded on the merged code: exactly three recordings changed, all from WP-0c (`auth.timeout` now clears the JWT and CSRF cookies, `field.info.unknown_id` 404, `field.info.over_cap` 400). History rewritten before any push: the mixed commit 501337e is now a harness commit followed by an inventory-and-recordings commit; the first review's verdict rows are carried in the WP file. Checks under Evidence.
- 2026-10-05 qa-2: status review.

## Review fixes

| # | Fix | Where |
|---|---|---|
| 1 | Images are always built (layer cache) and tagged by a hash of `requirements*.txt` and both Dockerfiles; no shared global tag. `stack/Dockerfile` names WP-0b as its removal trigger. | `stack/stack.sh` `build_images`, `stack/Dockerfile` |
| 2 | Every secret generated per stack and passed to web, web-init, redis and hasura. `compose.redis-auth.yaml` (requirepass) and `compose.hasura-secret.yaml` (admin secret) are added when the checked-out code reads `REDIS_PASSWORD` (WP-0b) or `HASURA_ADMIN_SECRET` (WP-0a), so the stack starts before and after either lands, in any merge order. On this branch WP-0a is merged and the Hasura overlay is active. There is no worker service: Celery runs tasks eagerly in web here. Overlay request to infra above. | `stack/compose*.yaml`, `stack.sh` |
| 3 | Secrets file in `$XDG_RUNTIME_DIR` (else `~/.local/state/harmony-contract`, mode 700), read line by line for known names only, refused unless owned by the user with mode 600 (also in `runner.Credentials`). All images pinned by digest; the base build pins `python:3.8` through `--build-context`. `CONTRACT_PROJECT`/`CONTRACT_WEB_PORT` documented per CI job. All services on an `internal: true` network; a forwarder publishes web. `create_user.py` no longer logs passwords on integration, so the `sed` redaction and the F4 request are gone. | `stack/`, `runner.py`, `INVENTORY.md` |
| 4 | `ruff format` at 88; replay marked `stack`; dev-group request to infra. | all `.py`, `test_replay.py`, `conftest.py` |
| 5 | Nested collections populated: pipeline runs seeded; role and group kept alive until the dashboard shares with them; new reads after `resource.update_roles` (`resource.roles.after_update`, `user.get.with_acls`, `group.find_by_name.with_acls_and_roles`) and after `user.generate_api_token` (`user.get.with_api_token`); alert filters non-empty. | `cases/` |
| 6 | `pin` takes `[]` and `{*}` tokens and records the sorted value set: user status, resource types, role names, configuration keys, granularities, policy types, alert checks. `DASHBOARD` vs `dashboard` is now a diff. | `cases.pin_value` |
| 7 | Cookies: `cleared`, `session` or `persistent` (Max-Age or Expires), `httponly`, `secure`, `samesite=<lowercase>`, `path`, `domain`. | `cases.describe_set_cookie` |
| 8 | A dropped pinned field is `pinned /x: ... recorded, missing now`; a failed capture is reported after the shape diff. `request_schema` is gone from recordings (request bodies live in the case files). | `cases.observe`/`compare`, `runner.run` |
| 9 | A declared map that is empty stays a map (`maxProperties: 0`); `role.num_users` and `digest_overview` declare `maps: ["$"]`. | `schema.infer`, `cases/` |
| 10 | Inventory: `GET /api2/query/table[/disaggregated]?h=` with 200/400/404 cases; the four `/dashboard/...` pdf and jpeg share links listed as deferred (Urlbox); a Relay table of all 51 operations, 40 recorded and 11 deferred, checked by `test_catalogue`; `storage/retrieve` recorded (seeded hit and unknown-slug 500); the configuration-list caller corrected; seed routes for pipeline runs listed. | `INVENTORY.md`, `cases/` |
| 11 | Phase-5 paragraph rewritten; pin counts corrected; bug notes on F2/F5 cases; python_client's unreachable fallback noted. | this file, `cases/` |
| 12 | Mixed commit split; `record.py` records and dry-runs only (replay is `pytest -m stack`); dry-run and `test_catalogue` share `catalogue.py`. | history, `record.py`, `catalogue.py` |

## Evidence

Re-run in full on 2026-10-05 from a clean clone of the branch head `f3ee4fd` (`git clone -b mig/WP-2c-api-contract-recordings` into `/tmp/wp2c-clean`, no local changes), Docker 29, Compose v5, uv 0.12. Live runs use `eval "$(tests/contract/stack/stack.sh env)"`.

- **Static**: `ruff format --line-length 88 --check tests/contract`: 16 files already formatted; `ruff check --line-length 88`: all checks passed.
- **Dry run**: `python -m tests.contract.record --dry-run`: `216 cases, 0 problems` (the same checks as `test_catalogue.py`).
- **Offline suite**: `pytest tests/contract -m "not stack"`: `49 passed, 216 deselected`.
- **Properties**: `test_schema.py` 21 passed under `--hypothesis-seed` 1, 2 and 3; the six-mutant run (`/tmp/wp2c_mutate.py /tmp/wp2c-clean`) killed all six.
- **Recording is reproducible**: on a fresh stack built from the clean clone, `python -m tests.contract.record` ran all 216 cases with no error or skip and left `git status` empty, so every recording reproduced byte for byte. Status mix: 166x 200, 18x 204, 1x 302, 11x 400, 4x 401, 10x 404, 1x 405, 5x 500. The 500s are F5, F9, F10 (two) and F11.
- **Replay, same stack**: `pytest tests/contract` (offline plus `stack`): `265 passed`, twice back to back. Every case cleans up after itself.
- **Replay, new stack**: `stack.sh down`, `stack.sh up`, then the same command: `265 passed`, twice.
- **Broken case turns red** (phase 2 exit check): with `isOfficial` set to `string` and `created` to `http-date` in `recordings/dashboard.get.json`, `pytest -m stack` reports `$.created: string format 'http-date' != 'date-time'` and the type mismatch, `1 failed, 215 passed`. The recording was restored and `git status` was empty again.
- **Merged code**: the branch includes `mig/integration` at `b81c235` (WP-0a, WP-0c, decisions 0003 and 0004). Re-recording after the first merge changed exactly `auth.timeout`, `field.info.unknown_id` and `field.info.over_cap`, which are all WP-0c contract changes. `git ls-files .playwright-mcp` is empty.
- **Isolation**: `docker compose ps` publishes only `forward` on `127.0.0.1:58650`. From the web container, `smtp.mailgun.org` and `api.urlbox.io` do not resolve and `1.1.1.1:443` is unreachable. Hasura runs with an admin secret (the WP-0a overlay is active); Redis runs without `requirepass` because WP-0b is not on the branch yet. The secrets file is mode 600 and owned by the user; `stack.sh down` removes it.
- **No secrets or PII in fixtures** (INV-6): `test_recordings_hold_no_values_that_look_like_secrets_or_pii` scans all 216 recordings for emails, JWTs and hex tokens. 27 values are pinned in 23 recordings: authorisation flags, the server version, configuration values, error messages, enum value sets (statuses, resource types, role names, configuration keys, granularities, policy types, alert checks), the import result and `timeout`. Pins that name secrets, or whose values look like emails or JWTs, are refused.

Limits:
- Deferred, each with its reason in `INVENTORY.md`: 18 of 146 routes (object storage, Dataprep, Urlbox rendering, `hierarchy` under the mock Druid, dead client code, a static GeoJSON asset) and 11 of 51 Relay operations (unpublished-field and self-serve mutations).
- Query responses come from Harmony's offline mock client, so they pin shapes, not numbers. Numbers belong to the golden suite (WP-2a). See "What phase 5 needs".

## What phase 5 needs (QA-2)

Pointing `CONTRACT_BASE_URL` at FastAPI does not work as the suite stands. A phase-5 WP must supply:

- **Login.** `runner.Runner.session` logs `admin*` sessions in through `POST /api2/authentication/login?set_cookie=true` and sends `X-Username`/`X-Password` for `client*` sessions. WP-5d changes both (C-5) and adds CSRF on unsafe methods (SEC-5). Make login and CSRF a hook the runner calls, chosen per target.
- **A route map.** Cases name `/api` and `/api2` paths; new endpoints live under `/api/v3/` (BE-5). Either the strangler keeps the old paths (nginx or FastAPI aliases), or each case gains a mapping from its legacy route to the v3 route, and recordings whose shape deliberately changes (the C-10 error envelope, columnar `QueryResponse`) are re-recorded in that WP with the reason.
- **Query data.** Query cases run against Flask's `ZEN_OFFLINE` mock client, which invents rows; the Druid stub answers `[]` to `groupBy`. FastAPI has no such mock, so its query routes would return empty shapes and fail. Give the stub fixed rows for the recorded queries (or run a small Druid with `harmony_demo` data, request above), and re-record queries once with Flask against that, so both stacks read the same rows.
- **Hasura.** The GraphQL cases go through Flask's proxy to Hasura; WP-5e retires both, so those recordings become the parity target for whatever replaces them.

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

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | changes-requested (re-review requested 2026-10-05) | 2026-10-04 qa-2c-review: offline suite, properties, stack isolation, replay on two fresh stacks, byte-identical re-recording and red-on-broken all reproduced. Fix: inventory misses GET /api2/query/table[/disaggregated]?h= and the dashboard /pdf and /jpeg share links; stack reuses a stale global base image (always build or tag by input hash); storage/retrieve deferral reason wrong; request_schema never compared; configuration list caller wrong. CI risks: floating image tags, fixed project name/port, internet-reachable web container. |
| reviewer | changes-requested (re-review requested 2026-10-05) | 2026-10-05 rev-2c: schema maths, properties, offline suite and inventory spot checks hold. Fix: the stack re-declares production services and stops starting once WP-0a/0b land (needs secrets; should be an infra-owned overlay shared with 2e/1a); stale global base image; CI breaks beside WP-2f (hypothesis; ruff format at 88); nested collections empty in every recording so item shapes unpinned; enum values and array pins unsupported; describe_set_cookie ignores Expires/Path/Domain and SameSite case; phase-5 replay claim does not work (login path, CSRF, route map, ZEN_OFFLINE mock); inventory gaps (pdf/jpeg, graphql 9 of ~50 ops); pinned/captured field drop gives traceback; map handling; request_schema unchecked; predictable credentials file sourced as shell; stale F4 claims; mixed commit. |
| security | n/a | |
