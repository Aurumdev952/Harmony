---
wp: "2e"
title: "Frontend unit and end-to-end harness"
status: building
owner_role: "qa"
instances:
  - name: "qa-5"
    files:
      - "e2e/**"
      - "tests/frontend/**"
      - "vitest.config.ts"
      - "package.json"
      - "yarn.lock"
      - "docs/modernisation/work/WP-2e.md"
      - "tests/golden/synth.py"
      - "tests/contract/stack/stack.sh"
branch: "mig/WP-2e-frontend-harness"
requirements: [QA-3, QA-4, FE-8, FE-9, INV-1, INV-5]
contracts_consumed: [C-5]
contracts_changed: []
security_review: false
---

# WP-2e: Frontend unit and end-to-end harness

qa-5 claimed this WP. Its session was lost when the host rebooted, and qa-5r took over on the same branch on 2026-10-04 with the untracked unit-harness start. qa-5r's session was lost in turn after unit 2; qa-5s took over on 2026-10-05 with its uncommitted unit-3 start (page table, AQT helpers, dashboard seed).

## Plan

Units, in order. Each line names the change and the check that ends it.

1. **Vitest unit harness** (`vitest.config.ts`, `tests/frontend/unit/`, `yarn test`). Covers Zen serialisers, `serializeForQuery` round-trips over every golden request (WP-2a cases), `$ref` reading (INV-4, C-11), `APIService` and `ZenClient` over a real loopback HTTP stub, API token generation, and date utilities including an exhaustive 1990 to 2040 Ethiopian calendar walk (INV-5). Check: `yarn test` green on host Node 24 and in `node:18.17` with `--network none`; `eslint` clean on the test files, because CI lints changed `.js` files; five client mutants each turn the suite red (`tests/frontend/mutants.sh`).
2. **Playwright e2e on the disposable stack** (`e2e/`: its own package with `playwright.config.ts`, `run.sh`, `stack/`, `support/`). The suite runs WP-2c's `tests/contract/stack` on its own project name and loopback port. Two additions make it work: a sidecar that serves the production client build where Flask's dev proxy expects webpack, and a Data Catalog seed (`populate_query_models_from_config.py` plus `stack/seed.sql`). Every test fails on an uncaught page error, a 5xx response, a failed request or any request that leaves the stack, unless that test allows the exact message with a reason. Check: `e2e/run.sh --grep @login` passes on a fresh stack and leaves no container or credentials file behind; `tsc --noEmit` (strict), shellcheck and ruff are clean.
3. **@smoke suite.** Login and logout; every page in the URL table opens without a server error or an uncaught page error; legacy URLs resolve (FE-9); one AQT query per visualization type; open, edit, share and export a dashboard; each auth flow (login failure, forgot password, reset link); the upload wizard opens. Check: `e2e/run.sh --grep @smoke` green twice on a fresh stack.
4. **@a11y axe baseline.** axe on every page at 1440 px. Today's serious and critical violations are recorded per page in `e2e/a11y/baseline.json`; a new rule id or a higher node count fails the test, and a fixed one tells you to shrink the baseline. FE-8 itself is met by WP-7c to 7e, which drive the baseline to empty. Check: green on the stack; a baseline with one rule removed turns red.
5. **Visual baseline** (`e2e/visual/`). Screenshots of every page at 390, 1024 and 1440 px with volatile regions masked; chart pages use the stack's deterministic Druid stub. Check: two consecutive runs on fresh stacks match the committed snapshots.
6. **Runner and CI hand-off.** `e2e/run.sh` builds the client if needed, brings the stack up, runs Playwright, writes the report, and always takes the stack down; `yarn e2e` calls it. A deliberately broken case turns it red (phase 2 exit check). Check: run from a clean clone of the branch head.

Deviation from the phase file (SHOULD, recorded here): phase-2 says Jest now and Vitest in phase 6. The unit harness uses Vitest 2.1.9 with Babel for Flow, so WP-6d does not need to port the tests. 2.1.9 is the newest Vitest whose engines accept the Node 18.17 that CI and the web-client image still run. WP-6b/6d can bump it with Node 24.

Playwright lives in its own package (`e2e/package.json`, `e2e/yarn.lock`), not in the root one. The root `.yarnclean` deletes every directory named `test` from `node_modules`, and that includes `@playwright/test` and parts of `playwright/lib`. The root package therefore keeps only Vitest and jsdom. The pins `@playwright/test` and `@axe-core/playwright` that 874562a added to the root moved to `e2e/`.

Depends on WP-2c for `tests/contract/stack/` (WP-2c is in review). Until WP-2c merges, this branch carries a merge of `mig/WP-2c-api-contract-recordings`, so the PR stacks on WP-2c.

## Contract changes

None.

## Requests

None of these block WP-2e.

- [ ] frontend-platform (WP-6a): `ZenClient.request` uses `$.getJSON` with no error callback, so on a 4xx or 5xx its promise never settles and callers hang (`web/client/util/ZenClient.js:41-56`, the TODO at line 44). `tests/frontend/unit/zenClient.test.js` holds a `test.todo('rejects on an HTTP error')`; turn it into a test when the fetch rewrite lands.
- [ ] frontend-platform: `APIToken.deserialize` parses the calendar dates `created` and `revoked` as UTC midnight and then converts them to local time (`web/client/services/models/APIToken.js:44-45`). West of UTC, `serialize` sends back the previous day. Repro: `TZ=America/New_York`, deserialize `{created: '2026-10-04', ...}` then serialize, and you get `'2026-10-03'`. Expected: the same date. The unit suite pins `TZ=UTC` until this is fixed. Then drop the pin and run the suite in a western zone as the failing-first test.
- [ ] frontend-platform: the dashboard text tile's Jodit editor fetches `js-beautify` and `ace` from `cdnjs.cloudflare.com` when it opens (Jodit's default source-mode config, `TextEditView/JoditEditor.jsx`). Offline or behind a strict CSP both loads fail and throw uncaught `Event` errors. Repro: `e2e/tests/dashboard.spec.ts` "a text tile added in the editor", with the `EDITOR_CDN` allowance removed. Expected: no request leaves the deployment. Drop the allowance when fixed.
- [ ] security, backend (WP-5c): `POST /api2/authentication/forgot_password` answers 400 "This user account does not exist" for an unknown address, while the page's success message ("If there is an account associated with the provided email address...") implies it does not reveal that (`USER_SHOW_USERNAME_EMAIL_DOES_NOT_EXIST = True`, `web/server/configuration/flask.py`). That is account enumeration. Repro: signed out, `/user/forgot-password`, enter `nobody@harmony.invalid`. The smoke suite asserts nothing about unknown addresses until the intended behaviour is decided.
- [ ] backend (WP-5h): `grid_dashboard_urlbox_renderer` catches the builtin `ConnectionError`, not `requests.exceptions.ConnectionError`, so an unreachable renderer turns a PDF or JPEG download into an unhandled 500 (`web/server/routes/views/page_renderer.py:138-148`). Repro: on the contract stack (no egress), Share > Download > PDF. The self-hosted renderer should fail with a handled error.
- [ ] backend: invite, reset and share e-mails on harmony_demo end "email us at None ( None )", and the reset mail links `mailto:None`: the support address is unset and the templates print it anyway. Repro: any mail in the e2e stack's mailpit.
- [ ] visualization (WP-7g): every map load sends Mapbox GL telemetry (`events.mapbox.com/events/v2`) and a billing session (`api.mapbox.com/map-sessions/v1`). The suite blocks both and allows them by name in `e2e/support/map.ts`; remove the allowance with the MapLibre move.
- [ ] infra (WP-2f): run `yarn test` on every PR (Node 18.17 today, about 7 s), and run `e2e/run.sh` in the job that can start Docker, publishing `e2e/report/` as an artifact.

## Log

- 2026-10-04 qa-5r: merged `mig/integration` (215f03b) into the branch, with no conflicts.
- 2026-10-04 qa-5r unit 1: Vitest unit harness, with 7 files and 339 tests plus 1 todo. Check: `yarn test` passes on Node 24 and in `node:18.17 --network none`; `eslint --max-warnings 0 tests/frontend` is clean; `tests/frontend/mutants.sh` reports 0 surviving mutants out of 5.
- 2026-10-04 qa-5r: merged `mig/WP-2c-api-contract-recordings` (fa72fe0) for `tests/contract/stack`.
- 2026-10-04 qa-5r unit 2: Playwright harness in `e2e/` on the contract stack, with a client-build sidecar, Data Catalog seed, error and external-request guard, and login specs. Check: `e2e/run.sh --grep @login` runs 4 tests, all passing, on a fresh stack, and teardown leaves 0 containers and no credentials file; `yarn --cwd e2e typecheck`, shellcheck and ruff are clean.

- 2026-10-05 qa-5s: merged `mig/WP-2c-api-contract-recordings` (b6e49b8) again, with no conflicts. Copied qa-5r's uncommitted unit-3 start from its worktree.
- 2026-10-05 qa-5s unit 3 (23da27f): the @smoke suite, 75 tests. Two stack changes made it possible. First, `e2e/stack/compose.e2e.yaml`, layered through a new `CONTRACT_OVERLAYS` hook in `stack.sh`, turns the offline mock off. The production Druid client then queries `e2e/stack/druid_broker.py`, which serves `tests/golden/synth.py` over HTTP. The mock had no subtotals or time-format columns, so hierarchy, sunburst, pie and number-trend 500ed on it, and its values were random. Second, `renderer.py` stands in for Urlbox, and the overlay adds a tmpfs for uploads. synth gained `extra_fields` and `dense` options; `tests/golden/record.py --check` reports 0 of 85 cases changed and `pytest tests/golden` passes (269). `seed.sql` repairs the contract stack's unpublished field: its `{"type": "SUM"}` calculation is a shape the pipeline never writes, and Indicator Setup throws on it. Check: `e2e/run.sh --grep @smoke` 75/75 twice on fresh stacks; `tsc --noEmit` strict, shellcheck on `e2e/run.sh`, and ruff check and format on `e2e/stack` and `tests/golden` are clean. The two shellcheck notes left in `stack.sh` (SC2174, SC2016) predate this WP.

## Evidence

- Unit 1: `yarn test` on host Node 24.12 gives 7 files, 339 passed and 1 todo, in 6.9 s. In `docker run --network none node:18.17 yarn test` it gives the same counts in 6.3 s, which proves the suite makes no external calls. Mutants from `tests/frontend/mutants.sh`, each applied to a scratch copy of `web/client` (it exits non-zero if any survive):

  | Mutant | Failing tests |
  |---|---|
  | `APIService` V2 prefix `/api2` to `/api` | 50 |
  | Pagume merge on month 12 instead of 13 (`dateUtil`) | 2 |
  | `APIToken.serialize` sends the secret token | 4 |
  | `convertURIToID` leaves the slash on the id | 46 |
  | `Zen.serializeArray` drops the first model | 2 |

  Under `TZ=America/New_York` two APIToken tests fail, with the dates off by one day. That is the second request above.
- Unit 2: `e2e/run.sh --grep @login --reporter=line` was run from `down`, so the stack was rebuilt from scratch. Every secret was regenerated, and the catalog and sidecar came up. The 4 login tests passed in 8.1 s. Afterwards `docker ps -a --filter label=com.docker.compose.project=harmony-wp2e-e2e` lists 0 containers and the credentials file is gone. The tests check four things: a signed-out redirect to `/login`, a UI sign-in that lands on `/overview` with an `HttpOnly` `accessKey` cookie, a wrong password that shows "Incorrect username and/or password." and sets no cookie, and a sign-out after which `/overview` redirects to `/login` again.

- Unit 3: `e2e/run.sh --grep @smoke --reporter=line` from `down`, run twice. Both runs: 75 passed in 2.7 min, exit 0. Afterwards 0 containers carry the project label and no credentials file is left (logs `/tmp/wp2e-smoke-run1.log`, `/tmp/wp2e-smoke-run2.log` on the build host). The suite covers:
  - `pages.spec.ts` (46): every page in the URL table under its legacy URL, the same pages under `/en/`, `/fr`, `/pt` and `/am` overviews rendered in that language, and a Data Catalog field URL loaded directly (FE-9, INV-5).
  - `visualizations.spec.ts` (20): every type the picker offers. Each test asserts a 200 from that type's query endpoint and a drawn element (a broker state or month label, data marks, or the primary number), and that no "No data" appears.
  - `dashboard.spec.ts` (6): a query from Analyze onto a new dashboard, then opened from the overview; a text tile saved and still there after reload; the share link; share by e-mail, checked in mailpit; and PDF and JPEG downloads, checked by magic bytes. The renderer refuses unless the minted cookie opens the dashboard.
  - `account.spec.ts` (2): an admin invite, then registration from the e-mailed link; forgot password, then reset from the e-mailed link, after which the old password fails and the new one works.
  - `upload.spec.ts` (1): CSV upload, mapping, review and complete, ending with the source queued.
  - `login.spec.ts` (4): unchanged.
- Faults the fixture catches that this unit does not hide: each allowance names its reason, and every one maps to a request above. These are Mapbox telemetry (maps), Jodit's cdnjs loads (text tile), and the data digest's missing object storage (WP-2c deferral).

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
