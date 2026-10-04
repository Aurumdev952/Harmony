---
name: harmony-qa
description: Harmony's test suites and the QA verdict procedure for migration work packages, covering golden query tests, authorisation tables, API contract recordings, pipeline fixtures, Playwright end-to-end, visual and accessibility checks, and the performance baseline. Use when building those suites (WP-1a, WP-2a to WP-2e) or when giving a QA verdict on any WP.
---

# QA for Harmony

Two jobs:
1. Own the cross-cutting suites under `tests/`, `e2e/` and `scripts/perf/`.
2. Give each WP an independent verdict based on evidence you produced yourself.

The suites are listed in `docs/modernisation/testing.md`.

## Building the suites

**Golden queries (WP-2a, `tests/golden/`).**
- Record `QueryRequest` payloads from the `harmony_demo` deployment, for every visualization type and every calculation type, with and without a query policy.
- Store `request.json`, `druid_query.json`, `druid_response.json` and `expected_response.json` per case.
- Replay offline: build the Druid query, feed it the recorded response and compare the shaped output.
- Normalise only what is truly volatile (timestamps of generation). Never normalise numbers.

**Authorisation table (WP-2b, `tests/authz/`).**
- Rows of (principal fixture, action, resource, expected allow or deny), covering every seeded role.
- Write it once against the Flask path. Later it runs against `harmony.core.authz.can()` and must agree case for case.

**Contract recordings (WP-2c, `tests/contract/`).**
- Capture method, path, query, body, status and response shape for every endpoint the frontend and `web/python_client` call.
- Replay the cases against Flask now and FastAPI later, per domain.
- Shape comparison checks types and keys. Values are compared where they are deterministic.

**Pipeline fixtures (WP-2d, `tests/pipeline/`).**
- One small CSV per input format `process_csv.py` supports.
- Assert output rows, `locations.csv` and `fields.csv` exactly.
- Load `property-based-testing:property-based-testing` for date parsing and the location join.

**End-to-end (WP-2e, `e2e/`, Playwright TypeScript).**
- Tags: `@smoke` (login, every page opens, one query per visualization type, open, edit, share and export a dashboard, each auth flow, the upload wizard), `@viz`, and `@a11y` (axe).
- Visual snapshots at 390, 1024 and 1440 pixels.
- A URL table that proves every legacy URL still resolves (FE-9).

**Performance (WP-1a, `scripts/perf/`).**
- Replays fixed requests and records p50 and p95, bytes and Druid time as JSON lines in `docs/modernisation/perf/`.
- `--compare` flags any p95 regression over 10% (PERF-7).

For browser automation, use the `playwright` plugin's MCP for exploration. Commit tests as Playwright test files. Generated tests must be read and owned, never committed blind.

## Giving a verdict

1. Check out the WP branch in your own worktree.
2. Read the WP's requirements, units and evidence. Do not trust claimed results. Re-run them:
   - the static checks for touched areas;
   - the suites relevant to the WP (golden for query changes, authz for permission changes, contract for API moves, pipeline for pipeline changes, `@smoke` for anything user-visible);
   - `verify` on every user-visible change, at three widths, plus the export path for dashboard changes;
   - the perf baseline for WPs that touch the query path or bundles.
3. For bug-fix units, confirm the new test fails on `main` and passes on the branch (QA-1).
4. Check the phase exit criterion in `testing.md` if this WP closes a phase.
5. Write the verdict in the WP file: `approved` or `changes-requested`, with numbered findings. Each finding gives the reproduction steps, expected and actual results, and the evidence path.

You never weaken a test to make it pass. A test that encodes old behaviour the spec deliberately changes is updated in the WP that changes it, with the reason in the WP log.
