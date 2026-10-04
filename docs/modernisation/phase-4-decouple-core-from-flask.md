# Phase 4. Decouple the core from Flask

Back to [overview](overview.md). Target layout: [03-target-architecture.md](03-target-architecture.md#package-layout).

**Goal.** Move the parts of the backend that do not care about HTTP into `harmony/core/`, with no Flask imports. When this phase ends, FastAPI, Celery, the pipeline and scripts all build the same `AppContext`, and every FastAPI route in phase 5 is a thin adapter. Run `pstack:architect` on `AppContext`, `Principal` and `QueryRequest` before writing code.

## 4a. Settings and deployment loading

- **Changes.**
  - Add `harmony/core/settings.py` (pydantic-settings) to replace `config/settings.py`.
  - Add `harmony/core/deployment.py`, which loads `config/<code>/` modules once and exposes them as one typed object.
  - Existing callers of `current_app.zen_config` (40 call sites) read from the context instead.
- **Data structures.**
  - `Settings` holds env-driven secrets and URLs.
  - `Deployment` holds the per-deployment modules: `general`, `ui`, `aggregation`, `datatypes`, `druid`, `indicators`, `filters`, `calendar`.
- **Verification.** A test builds a `Deployment` for `harmony_demo` and `template` without network access.

## 4b. Database access without `current_app`

- **Changes.**
  - Add `harmony/core/db.py`, which owns the engine and the session factory.
  - Change `web/server/data/data_access.py:4-17` so it delegates to it.
  - The 21 non-web files that use `Transaction` stop needing an app context.
- **Data structure.** `Database = {engine, session_factory}`.
- **Verification.** Run a pipeline script that writes to Postgres without `util/local_script_wrapper.py`'s app context.

## 4c. Druid client and datasource registry

- **Changes.**
  - Add `harmony/core/druid/`, a thin `httpx` client with timeouts and retries for native JSON and SQL queries.
  - Lift `DruidApplicationContext` (`web/server/data/druid_context.py`) into the core, replacing `current_app.cache.memoize` with an injected cache.
  - pydruid query objects stay for now. Only the transport changes.
- **Data structures.**
  - `DruidClient` exposes `query` and `sql`.
  - `DatasourceRegistry.current()` returns a `Datasource(name, version, last_modified)`.
- **Verification.** Golden tests pass against recorded responses through the new client.

## 4d. Query engine

- **Changes.**
  - Move `web/server/query/` and `data/query/` under `harmony/core/query/`.
  - Remove the Flask imports from `visualizations/util.py` and `query_request.py`.
  - Visualization handlers take `(request, client, datasource, principal)` explicitly. Most already do (`query_models.py:97-104`).
- **Verification.** The golden suite passes, and an import-linter rule forbids `flask` under `harmony/core`.

## 4e. Authorisation as pure functions

- **Changes.**
  - Add `harmony/core/authz/` with a `Principal` built from a user id and the database, and `can(principal, action, resource)`.
  - Port the needs logic from `web/server/security/permissions.py` and `signal_handlers.py`.
  - Flask-Principal stays in the Flask app as an adapter that builds a `Principal` from `g.identity` and calls the same functions. The adapter is deleted in phase 5d.
  - The query-policy filter takes a `Principal` instead of reading `g.identity`.
- **Data structure.** `Principal = {user_id, roles, acl_grants, query_policy_filter, is_bot, token_scopes}`.
- **Verification.** The policy suite from phase 2b runs against the pure functions and agrees with the Flask path case for case.

## 4f. `AppContext`

- **Changes.**
  - Add `harmony/core/context.py`, a frozen dataclass that holds settings, the deployment, the database, the Druid client, the datasource registry, the cache and the mailer.
  - Flask builds one at startup and stores it on the app.
  - The Celery worker (`web/server/workers/__init__.py`) builds its own without creating a Flask app.
- **Verification.** Celery sends an email in an integration test with no Flask app constructed.
