# Phase 5. FastAPI, domain by domain

Back to [overview](overview.md). Target design: [03-target-architecture.md](03-target-architecture.md#backend).

**Goal.** Move every HTTP surface from Flask to FastAPI, then delete Flask, Flask-Potion, Flask-User, Flask-Principal, Hasura and Relay.

**Method.**
- nginx routes `/api/v3/`, `/auth/` and `/render/` to FastAPI, and everything else to Flask.
- Both apps verify the same `accessKey` JWT.
- For each domain:
  1. Record the contract cases (phase 2c).
  2. Build the router on `harmony.core`.
  3. Switch the frontend callers to the generated client.
  4. Delete the Potion resource and its frontend service in the same PR.
- Run `pstack:show-me-your-work` throughout.

Breakage is acceptable only inside a domain's PR branch. `main` always serves every page.

## 5a. FastAPI skeleton

- **Changes.**
  - Add `harmony/api/app.py`. The lifespan builds `AppContext`.
  - Add a dependency that turns the `accessKey` cookie, a bearer token or the `X-Username`/`X-Password` headers into a `Principal`. It reproduces `login_from_request` (`web/server/security/signal_handlers.py:287-339`), including the API-token revocation check.
  - Add OpenTelemetry, a JSON logger, a request-id middleware and `/api/v3/health/live` and `/api/v3/health/ready`.
  - Add a uvicorn service to Compose and nginx routing for `/api/v3/`.
  - Generate the TypeScript client with `@hey-api/openapi-ts` in CI. A diff check fails the build if the generated client is stale.
- **Data structure.** `ApiError = {code, message, details}` as the single error envelope.
- **Verification.** A Playwright test logs in through Flask and calls `/api/v3/health/ready` with the same cookie.

## 5b. Query and data quality (22 routes)

- **Changes.**
  - Turn `QueryRequest` into a Pydantic v2 model with a published JSON Schema. Port the custom fields (`Field`, the `Calculation` union, the `QueryFilter` tree, `Granularity`) from `related` to discriminated unions.
  - Add async handlers that use the phase 1 cache, concurrent sub-queries, `to_thread` for shaping, and orjson responses.
  - Keep accepting `$ref` granularity strings through `harmony.core.refs.parse_legacy_ref`.
  - Switch the visualization `QueryEngine`s and `QueryInterface.js` to the generated client.
  - Delete `web/server/api/query/` and its Potion schemas.
- **Data structures.** `QueryRequest`, `QueryResponse = {columns, rows, totals?, meta}`.
- **Verification.**
  - Golden and contract suites pass against FastAPI.
  - Every AQT visualization type renders in Playwright.
  - The phase 1 baseline shows no p95 regression at 20 concurrent users, measured with a k6 or Locust script.

## 5c. Read-only metadata

- **Changes.** Port `metadata`, `data_digest`, `pipeline_run_metadata` and `dimension_values` (with search). Switch callers and delete the Potion resources.
- **Verification.** Contract suite. The Data Digest page works.

## 5d. Identity: authentication, users, groups, roles, policies

- **Changes.**
  - Under `/auth/*`: login, logout, forgot and reset password, register and invite accept, using single-use token rows in Postgres.
  - Outstanding Flask-User reset and invite tokens are verified by a legacy verifier that is deleted after their maximum lifetime has passed.
  - Add OIDC login through Authlib, behind a deployment setting.
  - Port the users, groups, roles, `resource-type`, `resource_role`, `query_policy`, `user_acl`, `group_acl` and `api-token` routers onto `harmony.core.authz`.
  - Delete Flask-User, the Flask-Principal adapter and the Potion signal hooks.
  - Set CSRF to double-submit on unsafe methods. Make the cookie lifetime configurable and add a refresh token.
- **Data structure.** `AuthToken = {id, user_id, purpose: reset|invite|confirm, token_hash, expires_at, used_at}`.
- **Verification.**
  - The policy suite against the router.
  - Playwright covers each auth flow and each Admin tab.
  - Run `pstack:interrogate` before merging.
  - A security review covers token storage, CSRF and session fixation.

## 5e. Catalog, Field Setup and Data Upload (retires Hasura)

- **Changes.**
  - Add `/api/v3/catalog/*` routers for categories, fields, field metadata, dimensions, calculations, unpublished fields and self-serve sources.
  - The full field list becomes one versioned document with an ETag. The client caches it in IndexedDB.
  - Rewrite the Relay screens in Data Catalog (about 43 files), Field Setup (about 16), Data Upload (about 8), the AQT form panel and `patchFieldService.js` on TanStack Query hooks.
  - Port the upload, export and import endpoints, including the multipart uploads and the subprocess call in `web/server/routes/api.py:196-207`. That subprocess becomes a Celery task.
  - Delete Hasura from Compose, `graphql/`, `scripts/db/hasura/`, the proxy route, `relay.config.js`, the Relay compiler and `babel-plugin-relay`, and all 33 `__generated__` directories.
- **Verification.**
  - Contract cases recorded through the Hasura proxy, with semantically equivalent responses (the field shapes change).
  - Playwright covers browsing the catalog, editing a field, publishing from Field Setup and running the upload wizard.

## 5f. Dashboards, sharing, alerts and configuration

- **Changes.**
  - Port the dashboard resource: 29 custom routes plus CRUD, sharing, sessions, user query sessions and storage.
  - Port alerts. If product chose to delete Alerts in phase 0, delete them instead.
  - Port the configuration resource. Its `before_create` hooks become explicit service calls.
  - Port the export routes onto the phase 1h Celery renderer.
  - Replace the Potion `where={...}` filters (30 call sites) with the shared filter vocabulary.
  - Update `web/python_client/`, which scripts use.
- **Verification.** Contract suite. Playwright covers creating, editing, sharing, cloning, presenting, embedding and exporting a dashboard.

## 5g. Rewrite stored `$ref` URIs

- **Changes.**
  - Add an Alembic data migration that walks dashboard specs, saved queries and alert definitions and rewrites `{$ref: '/api2/...'}` to `{id: ...}`. It is idempotent and logs every rewrite.
  - Delete `parse_legacy_ref`, `convertURIToID` and `convertIDToURI` (`web/client/services/wip/util.js:11-30`).
- **Verification.**
  - Run the migration on a copy of a production database. Every dashboard renders identically before and after, using Playwright screenshot comparison over all dashboards.
  - Run the migration twice and confirm nothing changes the second time.
  - Run `pstack:interrogate` before running it on any deployment.

## 5h. Pages and the end of Flask

- **Changes.**
  - FastAPI serves the page shells through Jinja on Starlette, using the Vite manifest helper from phase 6b, until phase 7f's single-page shell replaces them.
  - Add `GET /api/v3/session/bootstrap` to replace `window.__JSON_FROM_BACKEND`.
  - Delete `web/server/`, the gunicorn config, the Flask dependencies and the nginx split.
- **Verification.**
  - The full Playwright suite.
  - The repository contains no `import flask` anywhere.
  - The image is smaller, and its size is recorded.
