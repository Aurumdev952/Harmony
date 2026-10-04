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
2. A disposable `harmony_demo` stack (`tests/contract/stack/`): Postgres on tmpfs, redis, Hasura, mailpit, a fixed-answer Druid stub, and the production web-server image. Unique project name, only the web port published on loopback, admin password generated per stack outside the repo. Check: `stack.sh up` reaches a logged-in API call.
3. Recorder, runner and replay (`cases.py`, `runner.py`, `record.py`, `conftest.py`, `test_replay.py`, `test_cases.py`), with `--dry-run` that needs no network. Check: unit tests, and a record-then-replay round trip on the live stack.
4. Inventory (`INVENTORY.md`) of every endpoint `web/client` and `web/python_client` call, with the owning Flask route, plus the case files and recordings that cover it. `test_catalogue.py` keeps inventory, cases and recordings consistent and scans recordings for PII and secrets. Check: offline suite green; recording on a fresh stack, then replay green twice in a row.

Files: `tests/contract/**` only. No production code changes.

## Contract changes

None. This WP records the existing Flask contract; it changes no producer.

## Requests

None of these block WP-2c; each comes from a finding below.

- [ ] infra: pin `bcrypt==4.0.1` (or move off passlib) in `requirements.txt` so a fresh web image can hash and verify passwords (F3). Then `tests/contract/stack/Dockerfile` can go.
- [ ] infra: when WP-2f creates `pyproject.toml`, add `pytest`, `hypothesis`, `jsonschema` and `requests` to the dev group and run `pytest tests/contract` in CI (offline checks on every PR; replay in the job that brings up `tests/contract/stack`).
- [ ] frontend-platform: fix the raw-data export payload (F1). Either drop `includeNull`, `includeTotal` and `name` from `serializeForDisaggregatedQuery()`, or ask backend to accept them. Then re-record `query.table.disaggregated.client_payload`.
- [ ] frontend-platform: confirm whether the services behind F2 are dead code, and delete them or ask backend for the routes.
- [ ] backend: return 400 from `POST /api/validate_self_serve_upload` for a non-zip file (F5), and re-record `self_serve.validate.rejects_non_zip`.
- [ ] backend: make `web/python_client` log in through `POST /api2/authentication/login` with `email` and use the bearer token, instead of sending the password on every request (F7).
- [ ] backend: default `EMAIL_HOST` to nothing and skip sending when mail is unconfigured, instead of connecting to `smtp.mailgun.org` (F6).
- [ ] backend: make `PATCH /api2/user/<id>` return the updated user, not the function `update_user_groups` (F8), and re-record `user.update`.
- [ ] backend: answer `GET /api2/dashboard/<id>?legacy=1` for a dashboard with no legacy specification with a 404 or the current spec, not a 500 (F9).
- [ ] backend: fix `add_user_role` and `add_group_role` (`web/server/routes/views/users.py:187`, `groups.py:94`), which pass `resource_id` that `UserRoles`/`GroupRoles` no longer accept (F10). Re-record `user.update_roles.assign` and `group.update_roles.assign`.
- [ ] lead (path unowned): stop `scripts/create_user.py:348` from logging the plaintext password (F4).
- [ ] infra: object storage (minio) settings the web app accepts, added to the contract stack, so the data digest, thumbnail and data-upload routes can be recorded (deferred rows in `INVENTORY.md`).
- [ ] data-platform or infra: a small Druid with `harmony_demo` data for the contract stack, so `POST /api2/query/hierarchy` can be recorded (it 500s under the offline mock client).

## Log

- 2026-10-04 qa-2 unit 1: shape-only JSON Schema infer/merge/diff with property tests; check: `pytest tests/contract/test_schema.py` 18 passed (seeds 1-3 too); mutation run killed 6 of 6 mutants after adding the required-drift example.
- 2026-10-04 qa-2 unit 2: disposable stack in `tests/contract/stack/`; check: `stack.sh up` from nothing reaches `web is up`, login returns 200, `compose ps` shows only `127.0.0.1:58650->5000`, init log shows `password '[redacted]'`.
- 2026-10-04 qa-2 unit 3: recorder, runner, replay, dry-run; check: `pytest tests/contract/test_cases.py` green, `record.py --dry-run` lists every case without network, record-then-`--check` round trip green.
- 2026-10-04 qa-2 unit 4: `INVENTORY.md` (138 routes: 123 recorded, 15 deferred with reasons), 164 cases, 164 recordings, `test_catalogue.py`; check: offline suite 365 passed; recorded on a fresh stack, replay 529 passed twice on that stack and twice on a second fresh stack; a deliberately broken recording turns replay red.
- 2026-10-04 qa-2 unit 5 (lead request from WP-0c): `/api/field` unknown-id and over-cap cases, opt-in `cookies` observation (names and attributes only) on login, timeout and sign-out; check: unit tests 15 passed, fresh-stack record, replay 540 passed twice there and once on a second fresh stack.
- 2026-10-04 qa-2: status review.

## Evidence

All commands run from the worktree root on 2026-10-04 with Docker 29, Compose v5, uv 0.12. Environment for live runs: `eval "$(tests/contract/stack/stack.sh env)"`.

- **Offline suite** (no stack): `uv run --no-project --with pytest --with hypothesis --with jsonschema --with requests pytest tests/contract -q` gives `374 passed, 166 skipped` (the skips are the replay cases without `CONTRACT_BASE_URL`). `ruff check --line-length 120 tests/contract`: all checks passed.
- **Dry run**: `python -m tests.contract.record --dry-run` gives `166 cases, 0 with problems`.
- **Property tests**: `test_schema.py` (20 tests, 6 of them Hypothesis properties) passes under seeds 1, 2 and 3. A mutation run (`/tmp/wp2c_mutate.py`, six hand-made mutants of `schema.py`) killed all six. The leak property found a real gap (a key like `x@@y` escaped the data-key check), fixed in `52a18be`.
- **Recording**: on a fresh stack, `python -m tests.contract.record` recorded 166 cases with no error or skip. Status mix: 123x 200, 16x 204, 1x 302, 9x 400, 4x 401, 8x 404, 1x 405, 4x 500 (the 500s are F5, F9 and F10).
- **Replay, same stack**: full `pytest tests/contract` with `CONTRACT_BASE_URL` set gives `540 passed`, run twice back to back. Cases clean up after themselves, so a second run sees the same state.
- **Replay, new stack**: `stack.sh down`, `stack.sh up`, then the same command gives `540 passed`. Re-recording from a fresh stack also reproduced every earlier recording byte for byte; only the cases added for the WP-0c request changed. This proves no recording depends on the random mock data or database ids. It caught two recordings keyed by mock dimension values; those cases now declare `maps: ["$.totals"]`.
- **Broken case turns red** (phase 2 exit check): with `isOfficial` changed to `string` and `created` to `http-date` in `recordings/dashboard.get.json`, replay fails with `$.created: string format 'http-date' != 'date-time'` and the type mismatch, `1 failed, 163 passed`. The recording was restored afterwards.
- **No secrets or PII in fixtures** (INV-6): `test_recordings_hold_no_values_that_look_like_secrets_or_pii` scans every recording for emails, JWTs and hex tokens, and a manual grep for `@`, `eyJ`, `2026` and the run's names finds nothing. Only seven pinned values are stored (`/value`, `/success`, `/msg`, `/key`, `/data/timeout` and two `authorized` flags), and pinning refuses pointers that name secrets and values that look like emails or JWTs. The admin password lives in `$XDG_RUNTIME_DIR/harmony-wp2c-contract.env` (mode 600), is removed by `stack.sh down`, never appears in a case or a recording, and is kept out of `repr` and failure output.
- **Stack isolation**: `docker compose -p harmony-wp2c-contract ps` publishes only `127.0.0.1:58650->5000`. Mail goes to the in-stack mailpit, and Druid is a stub.

What phase 5 does with this (QA-2): point `CONTRACT_BASE_URL` at the FastAPI app (or nginx in front of both) and run `pytest tests/contract/test_replay.py`. A router passes when its cases pass. Any deliberate difference is re-recorded in that WP, with the reason in its log.

Limits:
- 15 routes are deferred. Each `deferred:` row in `INVENTORY.md` says why: object storage (data digest, thumbnails, data upload), the external Dataprep service, `hierarchy` under the mock Druid client, dead client code, and a static GeoJSON asset.
- Query responses come from Harmony's offline mock client, so they pin shapes, not numbers. Numbers belong to the golden suite (WP-2a).

## WP-0c interaction (lead request)

These cases record the behaviour on `main` today. `mig/integration` does not touch `web/server/routes/api.py`, so the shapes are the same there. WP-0c changes them and must re-record them, giving the reason in its log:

- `GET /api/field/<field_ids>`:
  - `field.info`: the summary is policy-filtered and carries the formula even at count 0.
  - `field.info.unknown_id`: becomes 404. Today it answers 200 with count 0 on this stack, because the Druid stub has no rows; against a datasource with rows it is a 500.
  - `field.info.over_cap`: 21 ids becomes 400. Today it answers 200.
- `POST /api/timeout`, `auth.timeout`: today a timed-out session gets `{"data": {"timeout": true}}` and **no** Set-Cookie (`cookies: []`), so the `accessKey` JWT cookie survives the logout. After WP-0c the recording should show `accessKey; cleared`.
- `GET /api/dimension/<name>/<value>`: WP-0c deletes it. No call exists in `web/client` or `web/python_client` (grep for `api/dimension` and `dimension/` URL builders finds nothing), it always returned 500, and it has no contract case. `INVENTORY.md` lists it under "Server routes no client calls".
- Related, for WP-5d (SEC-5): `auth.login.cookie` records `accessKey; httponly`, so the cookie is set without `Secure` and without `SameSite`.

## Findings

Found while recording. None is fixed here (QA never edits production code); each is a request below. Recordings encode today's behaviour, so the WP that fixes a finding updates its recording and says why in its log.

- **F1. Raw-data export sends a payload the server rejects.** `ShareQueryModal` calls `TableQueryResultState.runRawQuery`, which posts `QuerySelections.serializeForDisaggregatedQuery()` (`web/client/models/core/wip/QuerySelections/index.js:147-180`) to `POST /api2/query/table/disaggregated`. That payload carries `includeNull`, `includeTotal` and `name`, and the server's `QUERY_REQUEST` schema forbids extra keys.
  - Repro: stack up, then `record.py --only 'query.table.disaggregated.client_payload'`.
  - Expected: 200 with rows. Actual: 400 `Additional properties are not allowed ('includeNull', 'includeTotal', 'name' were unexpected)`. `QueryInterface.js:69` swallows the error, so the user sees an empty export.
  - Evidence: `tests/contract/recordings/query.table.disaggregated.client_payload.json`.
- **F2. Eight client endpoints have no server route.** `GET /api2/query/fields`, `/categories`, `/datasets`, `/dimensions`, `/dimensions/authorized`, `/field_metadata` (`web/client/services/wip/*Service.js`), `GET /api2/raw_pipeline_entity/search_metadata` (`services/EntityMatchingApp/EntityDimensionValueService.js:59`) and `GET /api2/alert_notifications/all_filtered` (`services/AlertsService.js:136`) all return 404. Evidence: the seven `*.missing_route.json` recordings and `alert_notification.all_filtered.json`. `patchLegacyServices()` swaps the field, dimension and field-metadata services onto GraphQL in the apps that call it (AQT, data quality, data digest, data upload). Anywhere else, and for categories, datasets and entity search, the REST call 404s. Either that client code is dead or a backend route went missing.
- **F3. A fresh web image cannot hash or verify passwords.** `bcrypt` is not pinned in `requirements*.txt`; a build today gets bcrypt 5.0.0, and passlib 1.7.4 then raises `ValueError: password cannot be longer than 72 bytes` on every hash and verify, so `create_user.py` fails and nobody can log in (INV-1).
  - Repro: `docker build -f docker/web/Dockerfile_web-server .`, then run `scripts/create_user.py` in it.
  - Workaround in the contract stack only: `tests/contract/stack/Dockerfile` installs `bcrypt==4.0.1`.
- **F4. `scripts/create_user.py:348` logs the plaintext password** of the user it creates (INV-6). The stack's `init.sh` redacts it with `sed`.
- **F5. Validating a non-zip self-serve upload returns 500, not 400.** `contains_valid_zipped_files` (`web/server/routes/views/validate_data_catalog.py:376`) raises on a file that is not a zip, so `POST /api/validate_self_serve_upload` answers with the generic 500 instead of its "does not contain the expected files" 400. Evidence: `recordings/self_serve.validate.rejects_non_zip.json`.
- **F6. An unconfigured stack mails through Mailgun.** `SMTP_CONFIG` defaults `EMAIL_HOST` to `smtp.mailgun.org` (`web/server/configuration/flask.py:123`). Without mail settings, every email-sending endpoint (dashboard create, invites, resets) stalls about 5 s connecting out before failing. The stack points mail at a local mailpit.
- **F7. `web/python_client` never logs in.** It posts to `/authentication/login`, which has no route. The answer is 405, not 404, so the client never tries its `/api/login` fallback; instead it sends `X-Username`/`X-Password` on every request (`web/python_client/core.py:32-46`). Evidence: `recordings/client.login_attempt.json`. The contract records that header mechanism (`client*` sessions) because it is what the client does today.
- **F8. `PATCH /api2/user/<id>` answers 200 with an all-null user.** The handler returns the function `update_user_groups` instead of the updated user (`web/server/api/user_api_models.py:150`), so the body is `$uri: /api2/user/None` and nulls. Evidence: `recordings/user.update.json` (types `null` throughout).
- **F9. `GET /api2/dashboard/<id>?legacy=1` returns 500** for a dashboard that has no legacy specification (any dashboard created since the spec upgrade): `_get_specification_version` calls `.get` on `None` (`web/server/routes/views/dashboard.py:50`). Evidence: `recordings/dashboard.get.legacy.json`.
- **F10. Assigning roles through a role map always returns 500.** `PATCH /api2/user/<id>/roles` and `PATCH /api2/group/<id>/roles` with any non-empty map raise `TypeError: 'resource_id' is an invalid keyword argument for UserRoles` (and `GroupRoles`) in `add_user_role`/`add_group_role` (`web/server/routes/views/users.py:187`, `groups.py:94`). Clearing roles with `{}` works. `web/python_client` (`directory_service/service.py:63, 124`) and the unused `DirectoryService.updateUserRoles`/`updateGroupRoles` send this shape. Evidence: `recordings/{user,group}.update_roles.assign.json`.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | changes-requested | 2026-10-04 qa-2c-review: offline suite, properties, stack isolation, replay on two fresh stacks, byte-identical re-recording and red-on-broken all reproduced. Fix: inventory misses GET /api2/query/table[/disaggregated]?h= and the dashboard /pdf and /jpeg share links; stack reuses a stale global base image (always build or tag by input hash); storage/retrieve deferral reason wrong; request_schema never compared; configuration list caller wrong. CI risks: floating image tags, fixed project name/port, internet-reachable web container. |
| reviewer | changes-requested | 2026-10-05 rev-2c: schema maths, properties, offline suite and inventory spot checks hold. Fix: the stack re-declares production services and stops starting once WP-0a/0b land (needs secrets; should be an infra-owned overlay shared with 2e/1a); stale global base image; CI breaks beside WP-2f (hypothesis; ruff format at 88); nested collections empty in every recording so item shapes unpinned; enum values and array pins unsupported; describe_set_cookie ignores Expires/Path/Domain and SameSite case; phase-5 replay claim does not work (login path, CSRF, route map, ZEN_OFFLINE mock); inventory gaps (pdf/jpeg, graphql 9 of ~50 ops); pinned/captured field drop gives traceback; map handling; request_schema unchecked; predictable credentials file sourced as shell; stale F4 claims; mixed commit. |
| security | n/a | |
