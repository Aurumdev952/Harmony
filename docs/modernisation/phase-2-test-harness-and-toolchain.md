# Phase 2. Test harness and toolchain

Back to [overview](overview.md). Strategy: [testing.md](testing.md).

**Goal.** Make every later change provable. Today the repository has no tests, so this phase writes the tests that pin current behaviour before the dependency floor moves. It also builds the CI that runs them.

## 2a. Golden query tests

- **Changes.**
  - Add `tests/golden/`. Record `QueryRequest` payloads from the demo deployment for every visualization type and every calculation type (sum, count, average, formula, exact unique count, complex), with and without query policies.
  - Snapshot two things: the built Druid query JSON (from `QueryRequest.to_druid_query()`) and the shaped response, built from recorded Druid responses.
- **Data structure.** `GoldenCase = {name, request.json, druid_query.json, druid_response.json, expected_response.json}`.
- **Verification.** `pytest tests/golden` passes without a live Druid, and the run takes under 60 seconds.

## 2b. Permission and policy tests

- **Changes.** Add table-driven tests over `web/server/security/permissions.py`, the resource managers in `web/server/potion/managers.py`, and `restrict_query_filter_to_user_permissions`. Each row is a principal, an action, a resource and the expected allow or deny.
- **Verification.** Every role type in the seed scripts has at least one allow case and one deny case.

## 2c. API contract recordings

- **Changes.**
  - Add a recorder that runs the demo deployment and captures request and response pairs for every `/api2` resource and blueprint route the frontend calls. That is 88 V2 call sites, plus the routes in the backend inventory.
  - Store them under `tests/contract/` with volatile fields such as timestamps and ids normalised.
- **Data structure.** `ContractCase = {method, path, query, body, status, response_shape}`.
- **Verification.** Replaying the cases against the running Flask app passes. Phase 5 replays the same cases against FastAPI.

## 2d. Pipeline fixture tests

- **Changes.** Add a small fixture CSV per input format `process_csv.py` supports. Assert the output rows, `locations.csv` and `fields.csv`. Do the same for `fill_dimension_data`.
- **Verification.** It runs in CI under CPython.

## 2e. Frontend unit and end-to-end harness

- **Changes.**
  - Configure Jest to run while still on webpack and Babel. Vitest replaces it in phase 6.
  - Add tests for the Zen model serialisers (`serializeForQuery`, `$ref` handling).
  - Add a Playwright smoke suite: log in, open each page, run one AQT query per visualization type, open a dashboard, export it.
- **Verification.** `yarn test` and `yarn e2e` pass locally and in CI against `docker compose` with the demo deployment.

## 2f. Toolchain

- **Changes.**
  - Add a root `pyproject.toml` with uv dependency groups (`web`, `pipeline`, `dev`) to replace the four requirements files. Keep the current pins in this step.
  - Replace black, pylint and the mypy config with ruff (lint and format) and mypy over the typed packages.
  - Have the CI workflow run lint, the type checks, pytest, the Jest tests and the Playwright smoke suite on every PR.
- **Verification.** CI is green, and a deliberately broken golden case turns it red.

## 2g. Structured logging

- **Changes.**
  - Replace the rotating 512 KB files in `log/config.py` with JSON logs on stdout.
  - Add a request id to every log line through middleware.
- **Verification.** `docker compose logs web | jq` parses, and each request's lines share an id.
