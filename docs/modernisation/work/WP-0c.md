---
wp: "0c"
title: "Fix the pure-mistake bugs"
status: building          # backend-2 builds on mig/WP-0c-pure-mistake-bugs-backend (decision 0001). core-1 wrote the tests, the patches and the SEC-4 decision.
owner_role: "backend"
instances:
  - name: "core-1"
    files:
      - tests/web/**
      - tests/infra/test_compose_environment_names.py
      - web/server/data/time_boundary.py
      - docs/modernisation/work/WP-0c/**
  - name: "backend-2"
    files:
      - web/server/routes/dashboard.py
      - web/server/routes/api.py
      - web/server/routes/views/query_policy.py
      - web/server/routes/views/dimension.py
      - web/server/util/authentication.py
      - web/server/util/util.py
      - web/server/util/template_renderer.py
      - web/server/routes/views/field.py
      - tests/web/test_timeout_route.py
      - tests/web/test_field_info_route.py
      - tests/web/test_no_raw_queries_from_routes.py
      - docs/modernisation/work/WP-0c.md
branch: "mig/WP-0c-pure-mistake-bugs"
requirements: [SEC-4, QA-1]
contracts_consumed: [C-5]
contracts_changed: []
security_review: true
---

# WP-0c: Fix the pure-mistake bugs

**Handover to backend-2.** Decision 0001 moved this WP to `backend`. core-1 has done the following on this branch:
- committed failing regression tests;
- deleted one unused core-owned method (`DataTimeBoundary.get_dimension_time_boundary`);
- proved every fix in a scratch copy of the tree;
- settled the `run_raw_query` question with `pstack:interrogate`.

The fixes for paths core does not own are ready as patches:
- `docs/modernisation/work/WP-0c/backend.patch` covers 7 files, including the deletion of the empty `views/dimension.py`.
- `docs/modernisation/work/WP-0c/infra.patch` covers `docker-compose.pipeline.yaml`.

Both pass `git apply --check` on branch head. Once both are applied, all 22 tests pass.

## How to run the tests

There is no `pyproject.toml` yet. The web server pins Python 3.8, Flask 1.0.1 and flask-jwt-extended 3.25.1. `uv run --with-requirements` rejects `-e git+...` lines, so rewrite them first:

```bash
sed -E 's/^-e (git\+.*#egg=(.*))$/\2 @ \1/; s/#egg=.*$//' requirements.txt requirements-web.txt \
  | grep -v 'segment-analytics\|google-cloud-logging\|Flask-Admin\|graphene\|Flask-GraphQL' > /tmp/reqs.txt
PYTHONPATH=$PWD uv run --no-project -p 3.8 --with-requirements /tmp/reqs.txt --with 'pytest<8' \
  python -m pytest tests/web tests/infra -q -p no:cacheprovider -W ignore
```

`tests/web/conftest.py` sets placeholder `DEFAULT_SECRET_KEY` and `DRUID_HOST`, and `ZEN_ENV=harmony_demo`, because the config modules read them at import time. It also provides `bare_flask_app`. Flask 1.0 cannot locate a test module loaded by pytest's rewrite hook, so the fixture passes the app's paths explicitly.

## Plan

| Unit | Change | Owner | Regression test | State |
|---|---|---|---|---|
| 1 | `docker-compose.pipeline.yaml`: delete `POSTGRES_DB_URI:=${POSTGRES_DB_URI}` and its comment. Nothing reads that variable: Alembic's `env.py` uses `SQLALCHEMY_DATABASE_URI`, which the same service already sets from `DATABASE_URL`. | infra | `tests/infra/test_compose_environment_names.py` | test committed; `infra.patch` |
| 2 | `dashboard.py:44`: redirect to `url_for('auth.unauthorized', locale=locale)`. The old code named the nonexistent `index.unauthorized` and returned a 500. It also forwarded `request.args` into `url_for`, so it must not be reintroduced (see the decision below). | backend | `tests/web/test_dashboard_unauthorized_redirect.py` (4 cases) | test committed; `backend.patch` |
| 3 | `is_session_persisted` moves into `web/server/util/authentication.py`. It reads a signed `remember_me` claim from the token that authenticated the request, and `login_user` signs that claim. | backend | `tests/web/test_session_persistence.py` (8 cases) | test committed; `backend.patch` |
| 4 | SEC-4: delete `AuthorizedQueryClient.run_raw_query` and make the wrapped client private (`_query_client`). | backend | `tests/web/test_authorized_query_client.py` | test committed; `backend.patch` |
| 5 | Delete `/api/dimension/<name>/<value>`, which returns 500 on every call because it calls a method that never existed. Also delete its empty `views/dimension.py` and the unused `get_dimension_time_boundary`. | backend (route); core (time_boundary) | `tests/web/test_api_routes.py` | core part committed (`bd71d45`); route in `backend.patch` |

### Unit 3 design

**The bug.** The old `is_session_persisted` looked for Flask-Login's `remember_token` cookie. Login goes through `web/server/util/authentication.py`, which sets the JWT `accessKey` cookie and never sets `remember_token`. So the function was always False, and the inactivity timeout (`web/client/util/timeoutSession.js`, which posts to `/api/timeout`) applied even to users who ticked "Remember me".

**Why a claim.** Browsers do not send a cookie's expiry back to the server. Both kinds of login issue a 365-day token, and only the cookie's `max_age` differs, so the server cannot tell them apart without a signal.

**The fix.**
- `create_user_access_token(..., remember_me)` adds `user_claims.remember_me`.
- `is_session_persisted()` calls `verify_jwt_in_request_optional()` and reads the claim through `get_jwt_claims()`.
  - This reads the same token, header first, that authenticated the request.
  - A missing, invalid, expired or foreign-signed token reads as False.
- The cookie is written under `current_app.config['JWT_ACCESS_COOKIE_NAME']`, not a literal.
- The function sits in the web-only authentication module because `web.server.util.util` is also imported in the pipeline image (`models/python/base.py`, `data/alerts/send_alert_notifications.py`), which does not install flask-jwt-extended or PyJWT.

**Effects.**
- **C-5 (backend's contract)** gains an additive claim. `_compute_token_provides` reads only `needs` and `query_needs`, so authorisation decisions are unchanged.
- **Existing sessions** carry no claim and read as not persisted, which matches today. Users get the fix at their next "Remember me" login.
- **API tokens** and the export-render token never had the claim, so they read as not persisted, which also matches today.
- **Security posture change (the security reviewer must accept this explicitly).** A "Remember me" user is now exempt from the client-side inactivity redirect for the cookie's 365-day lifetime. That was the original design intent, but it has not been true for as long as login has used the JWT cookie. If ministries want a cap on remembered sessions, that is a new rule for `/api/timeout`, not part of this fix.

## Decision: `run_raw_query` (SEC-4)

**Decision: delete `AuthorizedQueryClient.run_raw_query` and make the wrapped client private. Do not try to apply the policy to raw dicts. SEC-4 is not closed by this WP; see "Open SEC-4 items".**

**Process.** `pstack:interrogate` ran with three reviewers: A on opus, B on fable, and C on sonnet. C's report reached the lead and was relayed. All three agree on the decision, and all three say on their own that it does not by itself satisfy SEC-4.

**Options and reasoning.**
- **(A) AND the policy filter into `query['filter']`. Rejected.** A top-level AND does not reach nested `dataSource` subqueries, filtered aggregators or virtual columns, so it would look safe without being safe (C). `segmentMetadata` and `dataSourceMetadata` have no filter at all. A is workable for `timeseries` and `timeBoundary` (A), but that only matters for the system-client paths below, not for this method.
- **(B) Delete the method. Chosen.**
  - **Nothing calls it.** Every `run_raw_query` call site holds a system client: `druid_context` components, `db/druid/metadata.py`, the scripts, and the offline and static mock clients. All `AuthorizedQueryClient` consumers (`web/server/query/visualizations/*`, `web/server/query/data_quality/*`, `dashboard_api_models.py:821`) call only `run_query`. The class has no `__getattr__`.
  - **INV-3 holds.** Deleting the method changes no authorisation decision today (A, B and C all verified this).
  - **It shuts the door before anyone uses it.**
  - **The inner client becomes `_query_client`,** so `current_app.query_client.query_client.run_raw_query(...)` is no longer a public escape hatch (A).
- **(C) Keep the method but raise. Rejected.** It is the same as (B) plus dead code (all three).

### Open SEC-4 items (not fixed here; routed to the lead)

1. **`GET /api/field/<field_ids>`, which the frontend uses (`web/client/services/FieldInfoService.js`). Critical (A, B and C).**
   - **Path:** `api.py api_field_info`, then `views/field.py get_field_summary`, then `druid_context.row_count_lookup.get_row_count` and `data_time_boundary.get_field_time_boundary`, then the system client's `run_raw_query`.
   - **No policy is applied.** A user whose policy limits them to one district gets national row counts and first and last data dates for any field. Unknown ids give an empty filter, which returns the whole datasource's count and range.
   - **The caches leak across users.** `row_count_cache` and `time_boundary_cache` are process-wide, keyed by the raw `field_id`, shared across users and never evicted. Just applying the policy would make them leak one user's filtered numbers to the next.
   - **Recommended fix:**
     - run the count through `current_app.query_client.run_query`; `get_field_summary` already builds a `GroupByQueryBuilder`;
     - run the min/max through a policy-filtered query;
     - include the policy hash in the cache key (C-9 rule);
     - validate ids against known calculations and cap ids per request.
   - **Owner proposal:** backend for the route, core for the `druid_context` lookups, in WP-4e. Or a dedicated security WP if the lead wants it sooner. Because it changes numbers users see, it needs the golden and authz suites first.
2. **Other user-reachable system-client queries (B).**
   - `TemplateRenderer.build_ui_params` sends `minDataDate`, `maxDataDate` and `lastDataUpdate` from unfiltered time boundary and status data on every page.
   - `SourceStatus.load_ranges_from_druid` (`web/server/data/status.py:93`) calls `run_query` on the system client.
   - Neither takes user input, so both are datasource-wide metadata rather than injection paths. WP-4e still has to decide whether dates are policy-scoped.
3. **Structural guard (C).** Add a test that fails when `web/server/routes/**` or `web/server/api/**` reach `system_query_client`, `run_raw_query` or `druid_context.<lookup>.get_*` outside an allowlist. It would be red today because of item 1, so it belongs with WP-4e.
4. **Policy test on `run_query`.** Nothing yet tests that a non-superuser's `run_query` is ANDed with their policy filter (B). It belongs to the authz suite: request to qa for WP-2b.

### Other findings from the review

| Finding | Raised by | Category | Outcome |
|---|---|---|---|
| The first patch forwarded `request.args` into `url_for`. `?_external=1&_scheme=https://evil.example/x?` redirected off-site (A ran it to confirm), and `?endpoint=` or `?_method=` gave a 500. | A (critical), B, C | act on | Fixed. Redirect is now `url_for('auth.unauthorized', locale=locale)`, and the test covers all four cases. The `/unauthorized` page reads no query args. |
| `util.py` imported flask-jwt-extended and PyJWT at the top, which breaks pipeline-image imports | A, C | act on | Fixed by moving the function into `authentication.py`. A JWT-blocking import check passes for `models.python.base`, `web.server.util.util` and `data.alerts.send_alert_notifications`. |
| A second, divergent token decode: read the cookie although headers take precedence, and hard-coded `user_claims` | A, B, C | act on | Fixed. Uses `verify_jwt_in_request_optional()` and `get_jwt_claims()`. Test `test_bearer_token_without_the_claim_wins_over_a_remembered_cookie` covers the header case. |
| `POSTGRES_DB_URI` is read by nothing, so "fixing" its syntax has no effect | A, B, C | act on | Line and comment deleted. infra should also drop the `.env.example` entry (I did not read that file; settings deny it). |
| `/api/dimension/...` always returns 500 and would become an unfiltered lookup if repaired | A, B, C | act on | Route, empty view module and `get_dimension_time_boundary` deleted. |
| `/api/timeout` calls Flask-Login `logout_user()` but never clears the `accessKey` cookie, so the next request signs the user back in from the 365-day JWT. The inactivity timeout is only a client-side redirect. | A | consider: security | Pre-existing gap in a security control. Out of scope for "pure mistakes". Request to the lead: route to security for WP-5d, or a follow-up backend fix that deletes the cookie in `timeout_user_session`. |
| The cookie name has four definitions: `page_renderer.py:103`, `flask_user_views.py:41`, the config, and login | A, B | noted | Login now writes from config. The remaining literals belong to backend and are left for WP-5d (C-5). |
| `create_auth_response` has a redundant `remember_me` parameter | C | dismissed | It sets the cookie's `max_age`, so it is needed. |
| `conftest` sets environment variables at import time | C | noted | Needed because the modules read them at import, and `setdefault` keeps any real value. |
| Grep-driven test that every `url_for('<bp>.<name>')` literal resolves | B | consider | A cheap guard against the next dangling endpoint. Suggested to qa or backend as a follow-up, not added here. |

## Contract changes

C-5's token claims gain `user_claims.remember_me: bool`. The change is additive, and only `is_session_persisted` reads it. backend owns C-5, so backend-2 should acknowledge here when applying the patch:

- [ ] backend acknowledgement:

## Requests

- [ ] **backend (backend-2):** apply `docs/modernisation/work/WP-0c/backend.patch` with `git apply`. Run the tests (see "How to run"), commit per unit, run `verify` (see Evidence), then set `status: review`. Blocks units 2-5. Note that WP-0a (backend-0a) edits the Hasura proxy in `api.py`. This patch touches `api.py` only at its imports and at the dimension handler and route, so a rebase should merge cleanly.
- [ ] **infra:** apply `docs/modernisation/work/WP-0c/infra.patch`, which deletes `docker-compose.pipeline.yaml` lines 16-17. Also remove `POSTGRES_DB_URI` from `.env.example` if nothing else documents it. Blocks unit 1.
- [ ] **lead:** route the "Open SEC-4 items" above (item 1 is critical) and the `/api/timeout` cookie gap.
- [ ] **lead:** the phase docs say "Alembic uses POSTGRES_DB_URI" (`phase-0-security-and-subtraction.md` 0c). That is wrong and should become "delete the unused variable".
- [ ] **qa:** for WP-2b, add an authz case showing a non-superuser's `run_query` carries their policy filter.
- [x] **lead:** keep `/api/timeout` out of WP-0d. Done 2026-10-04.

## Log

- 2026-10-04 core-1: claimed the WP and merged `mig/decisions-0001-ownership` (decision 0001).
- 2026-10-04 core-1, units 1-4 tests (`20622b9`, `e6f51b5`, `be09dfe`): failing regression tests. Check: on the branch, 5 failed and 11 passed, each failure for its bug.
- 2026-10-04 core-1, interrogate: A on opus, B on fable, C on sonnet. Decision recorded above, and tests tightened (`978d61c`).
- 2026-10-04 core-1, unit 5 core part (`bd71d45`): deleted the unused `get_dimension_time_boundary`. Check: the module and `druid_context` import, black is clean, and no references remain.
- 2026-10-04 core-1, patches v2: proved in a scratch tree, which is branch head plus both patches. Check: `pytest tests/web tests/infra` gives 22 passed. App modules import. The pipeline import check passes with JWT blocked. `docker compose config` no longer emits `POSTGRES_DB_URI:`.

## Evidence

**Branch head, no fix:** 7 failed, 7 passed, 1 collection error.
- **compose:** `test_compose_environment_names[docker-compose.pipeline.yaml]` reports `sets invalid variable names: ["etl-pipeline: 'POSTGRES_DB_URI:'"]`.
- **redirect:** all 4 cases fail. The original failure was `werkzeug.routing.BuildError: Could not build url for endpoint 'index.unauthorized' ... Did you mean 'auth.unauthorized' instead?`
- **raw query:** `test_user_scoped_client_offers_no_unfiltered_raw_query` fails because `run_raw_query` is still present.
- **dimension route:** `test_broken_dimension_info_route_is_gone` fails because `api.dimension_info` is still registered.
- **session persistence:** the test module cannot import `is_session_persisted` from its new home. Commit `be09dfe` showed the behaviour failure at the old location: `test_remember_me_login_is_persisted` gave `assert False`, and `test_flask_login_remember_cookie_alone_is_not_persisted` gave `assert not True`.

**Scratch tree (branch head plus `backend.patch` and `infra.patch`):** `22 passed in 0.97s`.

**Compose before and after.** Before: `'POSTGRES_DB_URI:': postgresql://placeholder`. After, the environment is `COMMAND`, `DATABASE_URL`, `DEFAULT_SECRET_KEY`, `DRUID_HOST`, `SQLALCHEMY_DATABASE_URI` and `ZEN_ENV`, with no stray key.

**Pipeline import check** (meta-path finder blocking `jwt` and `flask_jwt_extended`). All of these pass after the patch: `models.python.base`, `web.server.util.util` and `data.alerts.send_alert_notifications`. With the first patch, all three failed (A).

**Lint.** `ruff check tests` is clean, and `black --skip-string-normalization -t py38` is clean on the tests and on `time_boundary.py`. On the patched production files, `ruff --select F` and black report only findings that are already on `main`: F401 in `api.py` and `template_renderer.py`, black on `api.py`, and black on `query_policy.py`. The patch adds none.

**Not yet run, for backend-2:**
- `verify` in the running app:
  - a user without view permission on a dashboard lands on `/<locale>/unauthorized`;
  - a "Remember me" login is not redirected by the inactivity timeout, and a normal login is;
  - the field-info tooltip still loads.
- The golden and authz suites, which do not exist yet (WP-2a, WP-2b).

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
