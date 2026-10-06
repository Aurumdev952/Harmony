# Testing and verification strategy

Back to [overview](overview.md).

Today the repository has no automated tests. Every phase in this plan assumes the suites below exist and stay green, so phase 2 builds them before any dependency moves.

## Suites

| Suite | Location | What it proves | Runs |
|---|---|---|---|
| Golden queries | `tests/golden/` | `QueryRequest` produces the same Druid query and the same shaped response | every PR, no Druid needed |
| Permissions and policies | `tests/authz/` | Every role allows and denies what it did before | every PR |
| API contract | `tests/contract/` | Every endpoint the frontend or `web/python_client` calls keeps its request and response shape | every PR against the running stack |
| Pipeline fixtures | `tests/pipeline/` | `process_csv` and `fill_dimension_data` produce the same rows | every PR |
| Frontend unit | `tests/frontend/unit/*.test.js` until WP-6a converts to TypeScript, then `web/client/**/*.test.ts` | Zen serialisers, `APIService`, token generation, date utilities including the Ethiopian calendar | every PR |
| Storybook interaction | `web/client/**/*.stories.tsx` | Each primitive's keyboard, focus and state behaviour | every PR |
| End-to-end smoke | `e2e/` (Playwright) | Log in; open every page; run one query per visualization type; open, edit, share, present and export a dashboard; each auth flow; upload wizard | every PR against `docker compose` with `harmony_demo` |
| Visual | `e2e/visual/` | Screenshots of every page and chart type at three widths | UI PRs |
| Accessibility | axe inside Playwright | No serious or critical violations | UI PRs |
| Performance baseline | `scripts/perf/` | p50 and p95 query latency, dashboard time to last tile, bytes | phase boundaries and performance PRs |
| Load | k6 or Locust | No p95 regression at 20 concurrent users | phase 5b and 5h |

## Rules for each unit

1. Rebase on `main`, then run the suites that cover the touched area before any change, so failures are attributed to the right unit.
2. Make one change.
3. Run static checks: lint, type check, unit tests.
4. Run on the real surface. For UI changes, run `verify` against the running app at three widths. For the pipeline, run it with `run` against `pipeline/harmony_demo`. For the API, replay the contract cases.
5. For a bug: a failing test first, then the fix in the same stack.
6. Do not start the next unit until this one is green.

## Phase exit criteria

| Phase | Exit check |
|---|---|
| 0 | No unintended published ports; startup refuses default secrets; every page renders |
| 1 | Baseline shows the expected gains; golden outputs are unchanged |
| 2 | CI runs every suite above that exists by then, and a deliberately broken case turns CI red |
| 3 | Every process runs on CPython 3.13 with supported libraries; all suites green |
| 4 | Import-linter forbids `flask` under `harmony/core`; Celery runs without a Flask app |
| 5 | No `flask`, `flask_potion`, `flask_user`, Hasura or Relay anywhere in the repository; load test shows no p95 regression |
| 6 | No webpack, Flow, jQuery or bluebird; all pages pass smoke tests on React 19 |
| 7 | No SCSS; one SPA; axe clean in light and dark themes; offline dashboard test passes |
| 8 | Incremental month reindex proven; Druid on a supported release; Dagster runs a week unattended; warehouse decision recorded |

## Surfaces with no control skill

None. The web UI uses `verify`, and the CLI and pipeline use `run`. Native mobile is out of scope.
