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
      - "playwright.config.ts"
      - "package.json"
      - "yarn.lock"
      - "docs/modernisation/work/WP-2e.md"
branch: "mig/WP-2e-frontend-harness"
requirements: [QA-3, QA-4, FE-8, FE-9, INV-1, INV-5]
contracts_consumed: [C-5]
contracts_changed: []
security_review: false
---

# WP-2e: Frontend unit and end-to-end harness

qa-5 claimed this WP. Its session was lost when the host rebooted, and qa-5r took over on the same branch on 2026-10-04 with the untracked unit-harness start.

## Plan

Units, in order. Each line names the change and the check that ends it.

1. **Vitest unit harness** (`vitest.config.ts`, `tests/frontend/unit/`, `yarn test`). Covers Zen serialisers, `serializeForQuery` round-trips over every golden request (WP-2a cases), `$ref` reading (INV-4, C-11), `APIService` and `ZenClient` over a real loopback HTTP stub, API token generation, and date utilities including an exhaustive 1990 to 2040 Ethiopian calendar walk (INV-5). Check: `yarn test` green on host Node 24 and in `node:18.17` with `--network none`; `eslint` clean on the test files, because CI lints changed `.js` files; five client mutants each turn the suite red (`tests/frontend/mutants.sh`).
2. **Playwright e2e on the disposable stack** (`playwright.config.ts`, `e2e/stack/`, `e2e/run.sh`, login fixture). Runs WP-2c's `tests/contract/stack` with an e2e overlay that serves a production client build to the web container, on its own project name and loopback port. Check: `e2e/run.sh --grep @login` green on a fresh stack.
3. **@smoke suite.** Login and logout; every page in the URL table opens without a server error or an uncaught page error; legacy URLs resolve (FE-9); one AQT query per visualization type; open, edit, share and export a dashboard; each auth flow (login failure, forgot password, reset link); the upload wizard opens. Check: `e2e/run.sh --grep @smoke` green twice on a fresh stack.
4. **@a11y axe baseline.** axe on every page at 1440 px. Today's serious and critical violations are recorded per page in `e2e/a11y/baseline.json`; a new rule id or a higher node count fails the test, and a fixed one tells you to shrink the baseline. FE-8 itself is met by WP-7c to 7e, which drive the baseline to empty. Check: green on the stack; a baseline with one rule removed turns red.
5. **Visual baseline** (`e2e/visual/`). Screenshots of every page at 390, 1024 and 1440 px with volatile regions masked; chart pages use the stack's deterministic Druid stub. Check: two consecutive runs on fresh stacks match the committed snapshots.
6. **Runner and CI hand-off.** `e2e/run.sh` builds the client if needed, brings the stack up, runs Playwright, writes the report, and always takes the stack down; `yarn e2e` calls it. A deliberately broken case turns it red (phase 2 exit check). Check: run from a clean clone of the branch head.

Deviation from the phase file (SHOULD, recorded here): phase-2 says Jest now and Vitest in phase 6. The unit harness uses Vitest 2.1.9 with Babel for Flow, so WP-6d does not need to port the tests. 2.1.9 is the newest Vitest whose engines accept the Node 18.17 that CI and the web-client image still run. WP-6b/6d can bump it with Node 24.

Depends on WP-2c for `tests/contract/stack/` (WP-2c is in review). Until WP-2c merges, this branch carries a merge of `mig/WP-2c-api-contract-recordings`, so the PR stacks on WP-2c.

## Contract changes

None.

## Requests

None of these block WP-2e.

- [ ] frontend-platform (WP-6a): `ZenClient.request` uses `$.getJSON` with no error callback, so on a 4xx or 5xx its promise never settles and callers hang (`web/client/util/ZenClient.js:41-56`, the TODO at line 44). `tests/frontend/unit/zenClient.test.js` holds a `test.todo('rejects on an HTTP error')`; turn it into a test when the fetch rewrite lands.
- [ ] frontend-platform: `APIToken.deserialize` parses the calendar dates `created` and `revoked` as UTC midnight and then converts them to local time (`web/client/services/models/APIToken.js:44-45`). West of UTC, `serialize` sends back the previous day. Repro: `TZ=America/New_York`, deserialize `{created: '2026-10-04', ...}` then serialize, and you get `'2026-10-03'`. Expected: the same date. The unit suite pins `TZ=UTC` until this is fixed. Then drop the pin and run the suite in a western zone as the failing-first test.
- [ ] infra (WP-2f): run `yarn test` on every PR (Node 18.17 today, about 7 s), and run `e2e/run.sh` in the job that can start Docker, publishing `e2e/report/` as an artifact.

## Log

- 2026-10-04 qa-5r: merged `mig/integration` (215f03b) into the branch, with no conflicts.
- 2026-10-04 qa-5r unit 1: Vitest unit harness, with 7 files and 339 tests plus 1 todo. Check: `yarn test` passes on Node 24 and in `node:18.17 --network none`; `eslint --max-warnings 0 tests/frontend` is clean; `tests/frontend/mutants.sh` reports 0 surviving mutants out of 5.

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

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
