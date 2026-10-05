---
wp: "2e"
title: "Frontend unit and end-to-end harness"
status: review
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

qa-5 claimed this WP. Its session was lost when the host rebooted, and qa-5r took over on the same branch on 2026-10-04 with the untracked unit-harness start. qa-5r's session was lost in turn after unit 2; qa-5s took over on 2026-10-05 with its uncommitted unit-3 start (page table, AQT helpers, dashboard seed). qa-5s's session was lost after unit 3; qa-5t took over the same day with its uncommitted unit-4 start (`e2e/a11y/baseline.json`, `e2e/tests/a11y.spec.ts`).

## Plan

Units, in order. Each line names the change and the check that ends it.

1. **Vitest unit harness** (`vitest.config.ts`, `tests/frontend/unit/`, `yarn test`). Covers Zen serialisers, `serializeForQuery` round-trips over every golden request (WP-2a cases), `$ref` reading (INV-4, C-11), `APIService` and `ZenClient` over a real loopback HTTP stub, API token generation, and date utilities including an exhaustive 1990 to 2040 Ethiopian calendar walk (INV-5). Check: `yarn test` green on host Node 24 and in `node:18.17` with `--network none`; `eslint` clean on the test files, because CI lints changed `.js` files; five client mutants each turn the suite red (`tests/frontend/mutants.sh`).
2. **Playwright e2e on the disposable stack** (`e2e/`: its own package with `playwright.config.ts`, `run.sh`, `stack/`, `support/`). The suite runs WP-2c's `tests/contract/stack` on its own project name and loopback port. Two additions make it work: a sidecar that serves the production client build where Flask's dev proxy expects webpack, and a Data Catalog seed (`populate_query_models_from_config.py` plus `stack/seed.sql`). Every test fails on an uncaught page error, a 5xx response, a failed request or any request that leaves the stack, unless that test allows the exact message with a reason. Check: `e2e/run.sh --grep @login` passes on a fresh stack and leaves no container or credentials file behind; `tsc --noEmit` (strict), shellcheck and ruff are clean.
3. **@smoke suite.** Login and logout; every page in the URL table opens without a server error or an uncaught page error; legacy URLs resolve (FE-9); one AQT query per visualization type; open, edit, share and export a dashboard; each auth flow (login failure, forgot password, reset link); the upload wizard opens. Check: `e2e/run.sh --grep @smoke` green twice on a fresh stack.
4. **@a11y axe baseline.** axe on every page at 1440 px. Today's serious and critical violations are recorded per page in `e2e/a11y/baseline.json`; a new rule id or a higher node count fails the test, and a fixed one tells you to shrink the baseline. FE-8 itself is met by WP-7c to 7e, which drive the baseline to empty. Check: green on the stack; a baseline with one rule removed turns red.
5. **Visual baseline** (`e2e/visual/`). Screenshots of every page and every chart type at 390, 1024 and 1440 px (testing.md), with volatile regions masked; charts draw from the stack's deterministic Druid broker. The snapshots are rendered in the pinned Playwright image, so they do not depend on the host's fonts. Check: two consecutive runs on fresh stacks match the committed snapshots; a one-pixel change to a snapshot turns its test red.
6. **Runner and CI hand-off.** `e2e/run.sh` builds the client if needed (in the web-client image's pinned Node 18.17), brings the stack up, runs the visual, a11y and e2e projects in that order, writes a report per project, and always takes the stack down; `yarn e2e` calls it. A deliberately broken case turns it red (phase 2 exit check). Check: run from a clean clone of the branch head.

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
- [ ] visualization (WP-7g), not blocking: the line chart's first draw is not deterministic. The same LINE query (Cases by Month), drawn twice at 1440 px on the same stack, showed bimonthly month ticks once and quarterly ticks once. A window resize settles it, so `tests/visual.spec.ts` captures charts only after a resize. Repro: `e2e/run.sh visual --grep LINE` with the resize loop changed to capture before the first resize.
- [ ] infra (WP-2f): run `yarn test` on every PR (Node 18.17 today, about 7 s), and run `e2e/run.sh` with no arguments in the job that can start Docker, publishing `e2e/report/` (one folder per project) and, on failure, `e2e/test-results/` as artifacts. The job needs the following:
  - the client build (`yarn build`, or the build artifact);
  - pulls of `python:3.8.20-bookworm`, `python:3.12-slim` and the digest-pinned `mcr.microsoft.com/playwright:v1.56.1-noble` (3.7 GB);
  - about 12 minutes.
  `run.sh` already handles rootful Docker: it runs the image as the caller's uid. Compare the first CI run's visual results against `e2e/visual/` before making the job required, and report any drift to qa rather than adding tolerance.

## Log

- 2026-10-04 qa-5r: merged `mig/integration` (215f03b) into the branch, with no conflicts.
- 2026-10-04 qa-5r unit 1: Vitest unit harness, with 7 files and 339 tests plus 1 todo. Check: `yarn test` passes on Node 24 and in `node:18.17 --network none`; `eslint --max-warnings 0 tests/frontend` is clean; `tests/frontend/mutants.sh` reports 0 surviving mutants out of 5.
- 2026-10-04 qa-5r: merged `mig/WP-2c-api-contract-recordings` (fa72fe0) for `tests/contract/stack`.
- 2026-10-04 qa-5r unit 2: Playwright harness in `e2e/` on the contract stack, with a client-build sidecar, Data Catalog seed, error and external-request guard, and login specs. Check: `e2e/run.sh --grep @login` runs 4 tests, all passing, on a fresh stack, and teardown leaves 0 containers and no credentials file; `yarn --cwd e2e typecheck`, shellcheck and ruff are clean.

- 2026-10-05 qa-5s: merged `mig/WP-2c-api-contract-recordings` (b6e49b8) again, with no conflicts. Copied qa-5r's uncommitted unit-3 start from its worktree.
- 2026-10-05 qa-5s unit 3 (23da27f): the @smoke suite, 75 tests. Two stack changes made it possible. First, `e2e/stack/compose.e2e.yaml`, layered through a new `CONTRACT_OVERLAYS` hook in `stack.sh`, turns the offline mock off. The production Druid client then queries `e2e/stack/druid_broker.py`, which serves `tests/golden/synth.py` over HTTP. The mock had no subtotals or time-format columns, so hierarchy, sunburst, pie and number-trend 500ed on it, and its values were random. Second, `renderer.py` stands in for Urlbox, and the overlay adds a tmpfs for uploads. synth gained `extra_fields` and `dense` options; `tests/golden/record.py --check` reports 0 of 85 cases changed and `pytest tests/golden` passes (269). `seed.sql` repairs the contract stack's unpublished field: its `{"type": "SUM"}` calculation is a shape the pipeline never writes, and Indicator Setup throws on it. Check: `e2e/run.sh --grep @smoke` 75/75 twice on fresh stacks; `tsc --noEmit` strict, shellcheck on `e2e/run.sh`, and ruff check and format on `e2e/stack` and `tests/golden` are clean. The two shellcheck notes left in `stack.sh` (SC2174, SC2016) predate this WP.
- 2026-10-05 qa-5t: merged `mig/WP-2c-api-contract-recordings` (2c8928a) again, with no conflicts. Copied qa-5s's uncommitted unit-4 start from its worktree.
- 2026-10-05 qa-5t unit 4: the @a11y axe baseline, 21 tests. axe runs on each of the 20 pages in the URL table at 1440 px. `e2e/a11y/baseline.json` records the serious and critical violations per page and rule as node counts. A new rule or a higher count fails with the rule, its help text and the offending selectors. A lower count fails with "shrink its entry". A 21st test fails when the baseline names a page that is not in the table. `E2E_A11Y_UPDATE=1` rewrites only the pages that ran. Check: green on the stack, and a regenerated baseline is byte-identical; a mutated baseline turns 3 tests red; `tsc --noEmit` strict is clean.
- 2026-10-05 qa-5t unit 5: visual baseline, 80 tests and 120 snapshots (4.7 MB) in `e2e/visual/`. It covers the 20 pages of the URL table at 390, 1024 and 1440 px, plus the 20 chart types: each is drawn in Analyze, then captured at each width after a window resize. A new `visual` Playwright project runs only in `mcr.microsoft.com/playwright:v1.56.1-noble`, pinned by digest, through the stack's forwarder. The tolerance is a per-pixel colour threshold of 0.05 with `maxDiffPixels: 0` (round 2; it was 0.2). The overview's last-visit, created and view-count cells are masked. Three harness changes came with it:
  - `run.sh` runs three invocations in order, visual, then a11y, then e2e. The first two expect the stack as seeded, and the e2e project adds dashboards, users and sources.
  - The a11y and visual specs open pages through `openSettled`, which waits for spinners and Suspense placeholders to clear. Unit 4 had recorded data-upload's baseline on its loading skeleton (1 contrast node). Settled, the page has 4, so the baseline now says 4. A data-quality axe run had also caught a transient spinner.
  - The viz case table moved to `support/viz.ts` so that smoke and visual share it.
  `env.ts` checks the credentials file's owner with `process.getuid()`, which needs no passwd entry inside the container. Check: `e2e/run.sh` from `down`, twice: visual 80/80, a11y 21/21, e2e 76/76; one changed pixel turns its test red; tsc strict and shellcheck are clean.
- 2026-10-05 qa-5t: added the `present` dashboard flow that testing.md lists for @smoke and unit 3 missed. Toggling Present hides Add Content and keeps the tiles; toggling back restores the control.
- 2026-10-06 qa-5t unit 6: `run.sh` builds the client in `node:18.17.1-bookworm`, pinned by the digest that `docker/web/Dockerfile_web-client` uses, because the root packages' native modules (node-pty) do not compile on Node 24. It also installs the host Chromium for the a11y and e2e projects. Check: `yarn e2e` from a `git archive` of the head into an empty directory, with no node_modules and no build, is green. The same checkout with the data-status view raising an error fails in all three projects on exactly the data-status cases, exits 1, and leaves nothing behind. Then `yarn test` in `node:18.17.1 --network none` on that checkout gives 339 passed and 1 todo. Status set to review.
- 2026-10-06 qa-5t round 2, unit 1 (reviewer finding 1): the screenshot threshold drops from 0.2 to 0.05, still with `maxDiffPixels: 0`. The reviewer measured re-render noise in the pinned image of at most 2 levels per channel, on 13 of the 120 snapshots, and all of them pass at 0.05. No snapshot needed rebaselining. Check, failing first: lightening the login page's text from #313234 to #646567 (450 pixels) passed at 0.2 and fails at 0.05 with 323 pixels different. Then the full visual run passed 80/80 at 0.05.

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
- Unit 4: `e2e/run.sh up`, then `playwright test --grep @a11y`: 21 passed in 26.1 s, and with `--repeat-each=3` 63 passed in 52.0 s. One earlier run, before the repeat, printed `20 passed` as its last line; its full log was not kept, so a failure in it cannot be ruled out, and no later run reproduced one. A full `E2E_A11Y_UPDATE=1` run, and one limited to login and forgot-password, both rewrite `baseline.json` byte for byte (`cmp`). Mutation check: removing `login.button-name`, raising `admin-roles.color-contrast` from 94 to 95 and adding a `retired-page` entry turned exactly three tests red (`/tmp/wp2e-a11y-mutant.log` on the build host):
  - login: `new violations on /login`, `button-name: 0 -> 1 nodes`, target `.zen-dropdown-button__main-btn`;
  - admin-roles: `improved; shrink its entry`, `color-contrast: 95 -> 94 nodes`;
  - the page-table test: `retired-page`.
  The baseline holds 20 pages and 252 nodes, 184 of them `color-contrast` (on 19 pages). `html-has-lang` and `meta-viewport` occur on every page: `web/server/templates/layout.html` has `<html>` with no `lang`, and its viewport sets `maximum-scale=1.0, user-scalable=no`, which blocks zoom (WP-7c to 7e).
- Unit 5: `e2e/run.sh` (no arguments) from `down`, twice in a row, each on a newly built stack: visual 80 passed (2.5 min, then 2.1 min), a11y 21 passed, e2e 76 passed, exit 0. Afterwards 0 containers carry the project label and the credentials file is gone (`/tmp/wp2e-full-run4.log`, `/tmp/wp2e-full-run5.log`). Earlier fresh-stack runs on the way there (`/tmp/wp2e-full-run{1,2,3}.log`) found the three faults fixed above: the data-quality spinner in axe, the data-upload skeleton in a snapshot, and the data-upload baseline. Each run also matched the snapshots recorded on an earlier stack, so stack-to-stack determinism holds on this host.
  - Mutation: one pixel of `page-login-1440.png` set to red gives `1 pixels (ratio 0.01 of all image pixels) are different`, and the test fails (`/tmp/wp2e-visual-mutant.log`).
  - Guard: `--project visual` on the host fails before any screenshot with "the snapshots were rendered in the pinned Playwright image and only match there".
  - What the snapshots show today, for WP-7: at 390 px most pages overflow sideways, for example the overview table and the Analyze panel (the BAR chart's result panel is 480 px wide). Maps draw on a blank style, because `support/map.ts` serves the boundaries locally, and at 1024 px only one of the three state points is in view.
  - Not proven here: a run on another machine (CI). Everything renders in the pinned image, so the remaining source of drift is the CPU's software rasteriser (the map canvases). The infra request below asks that the first CI run be compared against these snapshots before the job is made required.
- Host note, outside the repository: after the reboot, rootless Docker containers could not resolve names through the router's DNS, so `stack.sh`'s always-run `docker build` failed on `github.com`. These runs went through a local `docker` wrapper that adds `--network host` to `docker build` only. The build still ran in full.
- Unit 6, from a clean checkout of 5f2194d (`git archive` into `/tmp/wp2e-clean`, with no `node_modules`, no `e2e/node_modules` and no client build). `yarn e2e` installed the e2e package, then `yarn install` (118 s) and `yarn build` (webpack, 66 s) in the Node 18.17 image, then built and seeded the stack: visual 80 passed, a11y 21 passed, e2e 76 passed, exit 0, in 497 s in total (`/tmp/wp2e-clean-run.log`). The visual snapshots therefore also match a client built from scratch.
  - Deliberately broken case (phase 2 exit check): in that checkout `PageRouter.data_status` (`web/server/routes/index.py`) raises `RuntimeError`. `yarn e2e` then fails with 3 visual cases (data-status at 390, 1024 and 1440), 1 a11y case (data-status) and 2 e2e cases (`/data-status` and `/en/data-status` open). Every other case passes, the exit code is 1, and no container or credentials file is left (`/tmp/wp2e-broken-run.log`).
  - Static checks at the head: `tsc --noEmit` (strict) on `e2e/` is clean; shellcheck 0.11 on `e2e/run.sh` is clean; `ruff check` and `ruff format --check` on `e2e/stack` and `tests/golden` are clean; `eslint --max-warnings 0 tests/frontend` is clean. The repository's ESLint config (babel-eslint and Flow, `.js` and `.jsx` only, which is all CI lints) does not apply to the TypeScript in `e2e/`, so strict tsc is the gate there.
- Round 2, unit 1: `e2e/visual/page-login-1440.png` with every pixel whose channels all lie in 0x28-0x48 raised by 0x33 (450 pixels; the text colour is #313234). At threshold 0.2: `1 passed` (`/tmp/wp2e-grey-at-0.2.log`). At 0.05: `1 failed`, `323 pixels (ratio 0.01 of all image pixels) are different` (`/tmp/wp2e-grey-at-0.05.log`). The snapshot was restored, and `run.sh visual` passed 80 at 0.05 on a fresh stack (`/tmp/wp2e-visual-0.05.log`).

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | changes-requested | 2026-10-06 Round 1 at 236c914: design sound; trial merge with f5d5993 clean and every gate green (lock, ruff, 3.8 guard 857 plus e2e and tests/golden, mypy 518, 13 suites, record --check 0, yarn test 342 on Node 18.17 offline, ESLint, strict tsc, shellcheck); full run.sh green (visual 80, a11y 21, e2e 76) with 0 containers left; a11y counts identical in the pinned image and on host Chromium; snapshot size acceptable in git; strict tsc acceptable as the TS gate for now. Medium: (1) playwright.config.ts:28 threshold 0.2 hides large colour regressions (#333 to #666 passes); measured re-render noise is at most 2 levels per channel on 13 of 120 snapshots and passes at 0.05; set 0.05 with maxDiffPixels 0 and replace the WP's tolerance wording with the measurement. (2) run.sh:69-73 ensure_client rebuilds only when sourcemap.json is missing, so after any client edit the harness serves a stale bundle and can report green; record the source tree hash and dirty state next to the build and rebuild on mismatch, or always build with an opt-out. Low: (3) env.ts:35, global-setup.ts:68 the admin accessKey session state is written to os.tmpdir() mode 664 and never deleted; write it under the stack's 0700 runtime dir and delete in stack_down. (4) pages.ts:23 the page error alternative matches every uncaught error; pin the exact message. (5) a11y.spec.ts:78-85 update mode loosens as easily as it tightens; make it shrink-only with a named override. (6) e2e/package.json:16 FE-2 requires TypeScript 6; bump from 5.9.3 and move moduleResolution to node16 or nodenext. (7) page-home and page-overview, page-alerts and page-not-found, page-simple-query and advanced-query are byte-identical snapshots; skip alias rows in the visual loop. (8) WP-2e.md:18 state that QA-4's CI half waits on the infra follow-up and list it as a deferral; request frontend-platform (WP-6e, FE-11) ESLint coverage of e2e TS with no-floating-promises. Nit: (9) stale comments at e2e/stack/seed.sql:4 and tests/golden/synth.py:1. Host cleanup: /tmp/harmony-wp2e-e2e-admin-state.json left by an earlier run. |
| security | n/a | |
