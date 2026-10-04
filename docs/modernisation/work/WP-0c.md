---
wp: "0c"
title: "Fix the pure-mistake bugs"
status: review            # backend-2 on mig/WP-0c-pure-mistake-bugs-backend (decision 0001). Open items listed under "Open SEC-4 items" and Requests.
owner_role: "backend"
instances:
  - name: "core-1"
    files:
      - tests/web/test_api_routes.py
      - tests/web/test_authorized_query_client.py
      - tests/web/test_dashboard_unauthorized_redirect.py
      - tests/web/test_session_persistence.py
      - tests/web/conftest.py
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
      - tests/web/test_query_policy_filter.py
      - docs/modernisation/work/WP-0c.md
branch: "mig/WP-0c-pure-mistake-bugs"
requirements: [SEC-4, QA-1]
contracts_consumed: [C-5]
contracts_changed: [C-5]
security_review: true
---

# WP-0c: Fix the pure-mistake bugs

**Handover to backend-2.** Decision 0001 moved this WP to `backend`. core-1 has done the following on this branch:
- committed failing regression tests;
- deleted one unused core-owned method (`DataTimeBoundary.get_dimension_time_boundary`);
- proved every fix in a scratch copy of the tree;
- settled the `run_raw_query` question with `pstack:interrogate`.

core-1 left the fixes for paths core does not own as patches. backend-2 applied `docs/modernisation/work/WP-0c/backend.patch` in one commit per fix (units 2-5); the index matched the whole patch afterwards (`git apply -R --check --cached`). The compose fix (`infra.patch`) moved to WP-0b with its test (unit 1). Both patch files are deleted from the branch now that they are applied or handed over; they stay readable at `32dca82`.

## How to run the tests

There is no `pyproject.toml` yet. The web server pins Python 3.8, Flask 1.0.1 and flask-jwt-extended 3.25.1. `uv run --with-requirements` rejects `-e git+...` lines, so rewrite them first:

```bash
sed -E 's/^-e (git\+.*#egg=(.*))$/\2 @ \1/; s/#egg=.*$//' requirements.txt requirements-web.txt \
  | grep -v 'segment-analytics\|google-cloud-logging\|Flask-Admin\|graphene\|Flask-GraphQL' > /tmp/reqs.txt
PYTHONPATH=$PWD uv run --no-project -p 3.8 --with-requirements /tmp/reqs.txt --with 'pytest<8' \
  python -m pytest tests/web -q -p no:cacheprovider -W ignore
```

`tests/web/conftest.py` sets placeholder `DEFAULT_SECRET_KEY` and `DRUID_HOST`, and `ZEN_ENV=harmony_demo`, because the config modules read them at import time. It also provides `bare_flask_app`. Flask 1.0 cannot locate a test module loaded by pytest's rewrite hook, so the fixture passes the app's paths explicitly.

## Plan

| Unit | Change | Owner | Regression test | State |
|---|---|---|---|---|
| 1 | `docker-compose.pipeline.yaml`: delete `POSTGRES_DB_URI:=${POSTGRES_DB_URI}` and its comment. Nothing reads that variable: Alembic's `env.py` uses `SQLALCHEMY_DATABASE_URI`, which the same service already sets from `DATABASE_URL`. | infra | `tests/infra/test_compose_environment_names.py` (removed here; recoverable from `32dca82`) | **moved to WP-0b** (lead routing). Test and `infra.patch` removed from this branch. |
| 2 | `dashboard.py:44`: redirect to `url_for('auth.unauthorized', locale=locale)`. The old code named the nonexistent `index.unauthorized` and returned a 500. It also forwarded `request.args` into `url_for`, so it must not be reintroduced (see the decision below). | backend | `tests/web/test_dashboard_unauthorized_redirect.py` (4 cases) | done (`638b9e4`); test drives the registered route and asserts the exact `Location` (`cf91896`) |
| 3 | `is_session_persisted` moves into `web/server/util/authentication.py`. It reads a signed `remember_me` claim from the token that authenticated the request, and `login_user` signs that claim. | backend | `tests/web/test_session_persistence.py` (8 cases) | done: claim `68aa48d`, reader `ce12e99` |
| 4 | SEC-4: delete `AuthorizedQueryClient.run_raw_query` and make the wrapped client private (`_query_client`). | backend | `tests/web/test_authorized_query_client.py` | done (`0cc1c6a`) |
| 5 | Delete `/api/dimension/<name>/<value>`, which returns 500 on every call because it calls a method that never existed. Also delete its empty `views/dimension.py` and the unused `get_dimension_time_boundary`. | backend (route); core (time_boundary) | `tests/web/test_api_routes.py` | done: core `bd71d45`, route `abf1fa9` |
| 6 | `/api/timeout` ends the session for real: unset the JWT cookies and log out of Flask-Login. Before, it only called `logout_user()`, and the next request signed the user back in from the 365-day `accessKey`. | backend | `tests/web/test_timeout_route.py` (4 cases) | done: test `a076b1a`, fix `a010c1c` |
| 7 | SEC-4 open item 1: `/api/field/<ids>` validates ids (404) and caps them at 20 (400), ANDs the caller's policy into both lookups, keeps the shared row-count cache for callers without a policy only, never runs a lookup with an empty field filter, and returns the formula whatever the count. All backend-side; no core edit needed. See "Decision: `/api/field`". | backend | `tests/web/test_field_info_route.py` (9 cases, real `RowCountLookup`, `DataTimeBoundary`, policy builder and auth decorator over a fake Druid) | done: red test `f99d24d`, fix and final tests `1a72037` |
| 9 | The policy AND built `{"type": "and", "fields": [null, <policy>]}` when the request filter was `EmptyFilter` (Druid rejects it), and crashed at build time when it was `None`. Now `and_policy_filter`: the policy alone for `None`/`EmptyFilter`, otherwise `Filter(and, [query_filter, policy])` exactly as before. The first fix (`64dc60e`) used pydruid's `&`, which appends into an existing `and` in place (flattening the request and mutating a shared filter); the unit 7 interrogate caught it and `a89c55d` replaced it. Found by WP-2a (golden case `policy_include_all_all_time`). | backend | `tests/web/test_query_policy_filter.py` (6 cases through `AuthorizedQueryClient.run_query`; pins the unchanged shape for selector and `and` filters, no mutation, and no policy for superusers or an empty policy) | done: `70ecd0e`, `64dc60e`, `3681cb7`, `a89c55d` |
| 10 | The policy now also reaches `GroupByQueryBuilder.dimension_filter`. `ExactUniqueCountAggregation.modify_query` rebuilds the inner groupBy from `dimension_filter` and clears the outer filter, so the policy on `query_filter` never reached Druid for such queries. This was latent: no checked-in config builds `ExactUniqueCountCalculation`. Only that modifier reads `dimension_filter` after construction, so other queries send exactly what the pre-WP decorator sent (pinned). Docstrings now state this invariant instead of claiming "every query carries the policy". Found by the reviewer at `60edb27`. | backend | `tests/web/test_query_policy_filter.py` (+2: modifier, unchanged ordinary query) | done: red `59c55d3`, fix `9158d00` |
| 8 | Structural guard, capability-based: an AST scan of `web/server/routes`, `web/server/api`, `web/server/query` and `web/server/util`. It flags any import from the modules that build or run Druid queries (`db.druid.query_client`, `db.druid.metadata`, `data.pydruid_query`, `pydruid.client`, and the `web/server/data` lookups and status modules). It also flags `system_query_client`, `run_raw_query`, `AuthorizedQueryClient._query_client` from outside, and any `druid_context` access other than the datasource identity attributes, aliases included. `ALLOWLIST` holds justified uses. `KNOWN_VIOLATIONS` holds open item 2's datasource-wide dates and must stay present, so the test fails when one is fixed. One hop only, as the docstring says. | backend | `tests/web/test_no_raw_queries_from_routes.py` (26 cases) | done: `34c7e7b`, widened `ef790b0` |

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
- **Existing sessions** carry no claim and read as not persisted. With unit 6 that now has an effect: see "Who sees what differently".
- **API tokens** and the export-render token never had the claim, so they read as not persisted, which also matches today.
- **Security posture change (security and the human must accept this; see "Who sees what differently").** Before WP-0c nobody was really signed out by the inactivity timeout. `is_session_persisted` was always False, so `/api/timeout` answered `timeout: true` for every idle user. But the `accessKey` cookie survived, so the client's redirect to `/login?timeout=1&next=...` found the user still authenticated, and `/login` sent them straight back to `next`. With units 3 and 6 together, and `AUTOMATIC_SIGN_OUT` on (the default, `keep_me_signed_in: True`), after `SESSION_TIMEOUT` idle (1800 s in both checked-in configs):
  - a user who did not tick "Remember me" is now really signed out and must log in again;
  - a "Remember me" session issued before this deploy carries no claim, so it is really signed out once; the next "Remember me" login carries the claim;
  - a "Remember me" session issued after deploy is not timed out at all: no toast and no bounce through `/login`, for the cookie's 365-day life. That was the original intent of "Remember me". A cap on remembered sessions would be a new rule for `/api/timeout`.

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

### SEC-4 items (status on each; open ones routed to the lead)

1. **Fixed in unit 7 (`1a72037`).** `GET /api/field/<field_ids>`, which the frontend uses (`web/client/services/FieldInfoService.js`). Critical (A, B and C).
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
3. **Done in unit 8 (`34c7e7b`).** Structural guard (C). It was red on the pre-unit-7 code (3 findings: `field.py` x2, `api.py` x1). Its allowlist now records item 2's `data_status_information` use in `data_upload_summary.py` and the health check.
4. **Policy test on `run_query`.** `tests/web/test_query_policy_filter.py` now drives `AuthorizedQueryClient.run_query` (policy builder mocked, including a prepared query with a query-modifying aggregation), and `tests/web/test_field_info_route.py` uses the real `_construct_authorization_filter` with real `QueryNeed`s. The authz suite case is still wanted: request to qa for WP-2b.
5. **Admin API tokens ignore their own `query_needs` (A, B, C; pre-existing, consider: security).** A token issued to a site administrator with `needs: ['*']` keeps `RoleNeed(admin)` (`_compute_token_item_needs`), so `SuperUserPermission().can()` is true and the token's `query_needs` never narrow it, in `run_query` and now in `/api/field` alike. `_compute_token_query_needs` has a superuser branch, which suggests tokens were meant to narrow admins. Unchanged here (INV-3); `caller_policy_filter`'s docstring states it. Needs a security decision (WP-5d or WP-4e).
6. **Restricted callers get no row-count cache (A, B, C; performance).** Up to 20 ids x 2 uncached raw Druid queries per request for users with a non-empty policy. Callers whose policy reduces to nothing now share the cache (same filter). A bounded, policy-keyed cache needs core's `RowCountLookup` (C-9 rule): request to core. The only live caller sends one id per request.
   The only live consumer, `useFieldFormula.js`, reads `formula` alone; nothing reads `count`, `startDate` or `endDate`. WP-4e can drop the two lookups from `/api/field` instead of building that cache.
7. **Filters built outside the query builder are not covered (reviewer).** `AuthorizedQueryClient.run_query` ANDs the policy into `query_filter` and `dimension_filter` only. A nested `dataSource` or filtered aggregator assembled elsewhere would escape it. Unit 10 covers the one modifier that exists; the authz suite (WP-2b) should add a case for each new query shape.
8. **Security lows (sec-0c), deferred to WP-5d (backend, C-5 and SEC-5):**
   - `/api/timeout` is a state-changing POST with no CSRF check, and `accessKey` has no `SameSite`. A cross-site POST can sign a user out (no data exposure).
   - Login writes the cookie with plain `set_cookie`, `/api/timeout` clears it with `unset_jwt_cookies` (which also emits refresh and CSRF deletions that were never set), and `logout()` uses a literal `delete_cookie('accessKey')`. WP-5d should replace all three with one end-session helper built on `unset_access_cookies`, with a test that path and domain match the login cookie.
   - Flask-User's built-in `POST /login` (endpoint `user.login`, Flask-WTF form) still exists and sets Flask-Login's `remember_token`, which `is_session_persisted` no longer reads. No UI posts to it: `AuthenticationService.login` uses `/api2/authentication/login?set_cookie=true`. A session started there is subject to the inactivity timeout, and `/api/timeout` ends it. WP-5d retires Flask-User.

### Other findings from the review

| Finding | Raised by | Category | Outcome |
|---|---|---|---|
| The first patch forwarded `request.args` into `url_for`. `?_external=1&_scheme=https://evil.example/x?` redirected off-site (A ran it to confirm), and `?endpoint=` or `?_method=` gave a 500. | A (critical), B, C | act on | Fixed. Redirect is now `url_for('auth.unauthorized', locale=locale)`, and the test covers all four cases. The `/unauthorized` page reads no query args. |
| `util.py` imported flask-jwt-extended and PyJWT at the top, which breaks pipeline-image imports | A, C | act on | Fixed by moving the function into `authentication.py`. A JWT-blocking import check passes for `models.python.base`, `web.server.util.util` and `data.alerts.send_alert_notifications`. |
| A second, divergent token decode: read the cookie although headers take precedence, and hard-coded `user_claims` | A, B, C | act on | Fixed. Uses `verify_jwt_in_request_optional()` and `get_jwt_claims()`. Test `test_bearer_token_without_the_claim_wins_over_a_remembered_cookie` covers the header case. |
| `POSTGRES_DB_URI` is read by nothing, so "fixing" its syntax has no effect | A, B, C | act on | Line and comment deleted. infra should also drop the `.env.example` entry (I did not read that file; settings deny it). |
| `/api/dimension/...` always returns 500 and would become an unfiltered lookup if repaired | A, B, C | act on | Route, empty view module and `get_dimension_time_boundary` deleted. |
| `/api/timeout` calls Flask-Login `logout_user()` but never clears the `accessKey` cookie, so the next request signs the user back in from the 365-day JWT. The inactivity timeout is only a client-side redirect. | A | consider: security | Fixed in unit 6 (`a010c1c`) at the lead's request: `unset_jwt_cookies` on the timeout response. The token itself stays valid until expiry if copied elsewhere (stateless JWT); revocation is WP-5d. |
| The cookie name has four definitions: `page_renderer.py:103`, `flask_user_views.py:41`, the config, and login | A, B | noted | Login now writes from config. The remaining literals belong to backend and are left for WP-5d (C-5). |
| `create_auth_response` has a redundant `remember_me` parameter | C | dismissed | It sets the cookie's `max_age`, so it is needed. |
| `conftest` sets environment variables at import time | C | noted | Needed because the modules read them at import, and `setdefault` keeps any real value. |
| Grep-driven test that every `url_for('<bp>.<name>')` literal resolves | B | consider | A cheap guard against the next dangling endpoint. Suggested to qa or backend as a follow-up, not added here. |

## Decision: `/api/field` (unit 7, SEC-4 open item 1)

**Decision: fix it in the backend view, without core edits.** `RowCountLookup.get_row_count(filter, cache_key)` and `DataTimeBoundary.get_filtered_time_boundary(filter)` already take a caller-built filter and an optional cache key. `views/field.py` therefore builds the filter (field filter AND caller policy) and chooses the cache key itself. The lookups still run on the system client as `timeseries` and `timeBoundary` queries. For these two query types a top-level filter is complete (core-1's review, reviewer A), so no nested `dataSource` or aggregator escapes the policy.

**Rules now in force** (`web/server/routes/views/field.py`, `web/server/routes/views/query_policy.py`):
- **Validation before any Druid work.**
  - More than `MAX_FIELD_IDS_PER_REQUEST` (20) ids returns 400.
  - An id outside `zen_config.indicators.ID_LOOKUP` returns 404. That is the table `get_indicator_by_id` reads, so an accepted id can never crash the formula lookup.
- **One policy decision per request.** `caller_policy_filter()` returns `None` for site administrators, for unregistered users under public access, and when the policy builds to nothing. Otherwise it returns the policy filter. `AuthorizedQueryClient.run_query`'s decorator uses the same function, so the field view and every other query share one rule (A, B, C asked for this).
- **Cache.** With no policy, the query and the row-count cache key (the field id) are byte-for-byte what they were. With a policy, the filter is `and_policy_filter(field_filter, policy)` and the shared cache is bypassed (`cache_key=None`). The process-wide `row_count_cache` therefore only ever holds numbers for callers who see the whole datasource.
- **The time boundary no longer passes a cache key.** In the web app, `druid_context.data_time_boundary` builds a new `DataTimeBoundary` per access, so the old `field__<id>` key never outlived a request. `PopulatingDruidApplicationContext` caches the property, but only scripts use that class (A, B).
- **No lookup without a field filter.** A configured field whose filter is empty, because its constituents are missing (`INCOMPLETE_CALCULATED_INDICATORS`) or because of an unfiltered aggregation (a theta sketch with no `filter_field`, `HyperUniqueCount`), would count every row the caller can see. It now reports `count: 0` and runs no query (A, B, C).
- **The formula is configuration** and is returned whatever the count (A, B, C, answering the open question). Only `count`, `startDate` and `endDate` depend on the caller's slice. When the slice has no time boundary, the row-count query is skipped.

**Intended differences for callers who already saw everything (INV-2; reviewer to accept):**

| Case | Before | After |
|---|---|---|
| Field with rows | count, dates, formula | identical: same Druid queries, same cache key |
| Field with no rows | `count: 0`, `formula: null` | `count: 0`, formula returned |
| Configured field with an empty filter | whole-datasource count and dates (not the field's rows) | `count: 0`, no Druid query, formula returned |
| Id not in the indicator config (garbage, or a data-catalog-only field) | 500 (`get_indicator_by_id` dereferenced `None`) once the datasource had rows | 404 before any Druid work |
| More than 20 ids | every id queried | 400 |

Restricted callers now see only their slice. That is the intended INV-3 change and SEC-4.

**Interrogate.** Three reviewers ran on the first version of the fix: A on opus, B on fable, and C on sonnet (C's report came through the lead). All three found no path where a restricted caller gets unfiltered numbers or another user's numbers. All three also found that callers with no policy get unchanged queries and cache keys.

| Finding | Raised by | Category | Outcome |
|---|---|---|---|
| "No aggregations" was a proxy for "unknown id". It 404'd configured calculated indicators with missing constituents, and it missed configured fields whose filter is empty anyway. | A, B, C | act on | Known now means `ID_LOOKUP` membership. An empty field filter is a separate, explicit outcome (count 0, no query). |
| The policy decision was re-evaluated per id: a config DB read and a policy build each time. The policy branch was copied into the view. | A, B, C | act on | `caller_policy_filter()` runs once per request and is shared with the `run_query` decorator. `_FieldRows` holds the lookups and interval for the request. |
| Return the formula regardless of count | A, B, C | act on | Done; pinned by `test_empty_slice_has_no_numbers_but_keeps_the_formula`. |
| The tests mocked the authorisation inputs and the cache | A, B, C | act on | The tests now use the real `RowCountLookup`, `DataTimeBoundary`, `_construct_authorization_filter` with `QueryNeed`s, and the `authentication_required` decorator. Users are run in turn (admin, restricted, admin) against one cache. |
| Dead code: `FieldsApi(row_count_lookup)` and `ApiRouter` plumbing; `DataTimeBoundary.get_field_time_boundary` has no callers | B, C (A for the core method) | act on | Backend plumbing deleted. The core method is a request to core. |
| `pydruid` `&` appends into an existing `and` filter in place | A (in passing) | act on | This exposed a regression in my unit 9 fix: and-shaped request filters were flattened and mutated. Fixed (`3681cb7`, `a89c55d`) with `and_policy_filter`, which always builds a new filter. |
| Admin API tokens ignore their own `query_needs` | A, B, C | consider: security | Pre-existing parity with `run_query`. Open item 5; docstring states it. |
| Restricted callers have no row-count cache | A, C | consider | Open item 6; request to core for a bounded, policy-keyed cache. The row count is skipped when the slice has no time boundary. |
| 400/404 return werkzeug HTML and are logged at ERROR with a traceback | B, C | noted | Every `/api` 4xx in this app does the same (`error_handlers.py`). The old behaviour for these ids was a logged 500. The JSON envelope is C-10, landing in the FastAPI port. |
| `ZenClient.request` (`$.getJSON`, success callback only) never settles on a 4xx, and `LegacyIndicatorAboutPanel` asks `/api/field` about data-catalog-only fields | B, C | noted | Same visible result as the old 500: no formula. Request to frontend-platform. |
| `hide_constituents` indicators expose their formula | A | noted | Pre-existing: formulas were already returned whenever count > 0. The constituent names are visible through `/api2/query/fields`. |
| `is_unrestricted_query_caller` may return a non-bool | C | dismissed | The function was replaced by `caller_policy_filter`, which returns `None` or a filter. |

## Who sees what differently

This table is for security and the human to accept: every user-visible difference this WP makes. Unit 1 moved to WP-0b. Unit 8 is a test.

| Unit | Who | Before | After | Accept as |
|---|---|---|---|---|
| 2 | Signed-in user opening a dashboard they may not view | 500 page | 302 to `/<locale>/unauthorized` on the same host; query args are not forwarded | bug fix |
| 3 + 6 | User who did not tick "Remember me", idle for `SESSION_TIMEOUT` (default 30 min) with automatic sign-out on (default) | toast, bounce through `/login`, still signed in (cookie kept) | really signed out; `accessKey` cleared; must log in again | **security posture change** (the control now works) |
| 3 + 6 | "Remember me" session issued **before** deploy, idle | same bounce, still signed in | really signed out **once**; the next "Remember me" login is exempt | **one-off sign-out at deploy** (release note) |
| 3 | "Remember me" session issued **after** deploy, idle | bounce, still signed in | no timeout: no toast and no bounce, for the cookie's 365 days | intended "Remember me" behaviour |
| 3 + 6 | API-token and export-render callers | not affected (no browser timer) | not affected | none |
| 5 | Anyone calling `GET /api/dimension/<name>/<value>` | 500 on every call | 404 (route gone); no UI calls it | bug fix |
| 7 | User with a query policy, field-info API | whole-datasource row count and first/last dates for any field | count and dates within their policy only; formula always returned | **INV-3 narrowing (SEC-4)** |
| 7 | Site administrator or public-access visitor, field-info API | count, dates; formula only when count > 0 | same numbers from the same queries; formula also at count 0; 0 instead of whole-datasource numbers for a configured field with no filter of its own | INV-2 difference (see the `/api/field` decision) |
| 7 | Any caller: unknown id, or more than 20 ids | 500 (unknown id once the datasource had rows), or every id queried | 404, or 400 | bug fix |
| 9 | User with a query policy running a query whose built filter is empty (golden case `policy_include_all_all_time`) | Druid rejected `and[null, policy]`: an error | results limited to their policy | bug fix |
| 9 | Every other query | `and[filter, policy]` | identical | none |
| 10 | User with a query policy, query using an exact-unique-count calculation | policy dropped in the inner query (latent: no config uses it) | policy applied | latent leak closed |

**Release note (for the deploy that ships WP-0c).** "Sessions now really end after the inactivity timeout (30 minutes by default) unless you ticked *Remember me* when you signed in. If you ticked *Remember me* before this update, you will be asked to sign in once more after a period of inactivity; tick it again to stay signed in. Users with a data-access policy now see field record counts and date ranges for their own data only."

## Contract changes

C-5's token claims gain `user_claims.remember_me: bool` (listed in `contracts_changed`). The claim is additive and only `is_session_persisted` reads it. It does change behaviour: together with unit 6 it decides who the inactivity timeout signs out (see "Who sees what differently"). backend owns C-5:

- [x] backend acknowledgement: backend-2, 2026-10-04. backend owns C-5 and is also its only consumer here. Old shape: `user_claims = {needs, query_needs}`. New shape: `user_claims = {needs, query_needs, remember_me: bool}`, written only by `create_user_access_token` (login, and the non-cookie login that returns the token in JSON with `remember_me` False). Readers: `is_session_persisted` reads `remember_me`; `_compute_token_provides` (`signal_handlers.py`) and `api.py` read only `needs`/`query_needs`, so authorisation is unchanged (INV-3). API tokens and the export-render token (`page_renderer.py`) carry no claim and read as not persisted. No migration: tokens without the claim read as False, which is today's behaviour. The FastAPI `PrincipalDep` (WP-5a) must ignore unknown `user_claims` keys.

## Requests

- [x] **backend (backend-2):** apply `docs/modernisation/work/WP-0c/backend.patch`, commit per unit. Done 2026-10-04 (units 2-5). Note that WP-0a (backend-0a) edits the Hasura proxy in `api.py`; this branch touches `api.py` at its imports, the dimension handler and route, `timeout_user_session` and `api_field_info`.
- [x] **infra (moved to WP-0b by the lead):** delete `docker-compose.pipeline.yaml` lines 16-17 and drop `POSTGRES_DB_URI` from `.env.example` if nothing else documents it. The regression test `tests/infra/test_compose_environment_names.py` and `infra.patch` are no longer on this branch; infra-0b can take them from `32dca82` (`git show 32dca82:tests/infra/test_compose_environment_names.py`, `git show 32dca82:docs/modernisation/work/WP-0c/infra.patch`).
- [x] **lead:** route the "Open SEC-4 items" above and the `/api/timeout` cookie gap. Item 1 and the cookie gap were routed back to this WP and are fixed (units 7 and 6); item 3 is unit 8.
- [ ] **lead:** route open SEC-4 items 2 (datasource-wide dates: page bootstrap, data status page, `data_upload_summary`; pinned in the guard's `KNOWN_VIOLATIONS`), 5 (admin API tokens ignore their `query_needs`; security decision), 6 (row-count cache for restricted callers, or drop the lookups), 7 (filters built outside the query builder) and 8 (security lows) to WP-4e / WP-5d.
- [x] **core:** delete `DataTimeBoundary.get_field_time_boundary` and its cache. Done by core-1 on `mig/WP-0c-pure-mistake-bugs-core` (`21a6d89`), merged here.
- [ ] **core (WP-1b or WP-4e):** give `RowCountLookup` a bounded cache keyed on (field filter, policy filter digest) so restricted callers can share cached counts safely (open item 6). Today `row_count_cache` is an unbounded `defaultdict`. Blocks nothing.
- [ ] **frontend-platform:** `ZenClient.request` (`web/client/util/ZenClient.js`) uses `$.getJSON` with only a success callback, so a 4xx or 5xx never settles the promise. `/api/field` now answers 404 for ids outside the indicator config. That is the case for data-catalog-only fields that `LegacyIndicatorAboutPanel` asks about; they were a 500 before. Reject on error, and only ask `FieldInfoService` about config fields, or retire it when this domain moves to FastAPI. Blocks nothing.
- [ ] **core or backend (WP-0d):** delete `web/server/util/dev/static_data_query_client.py`. Nothing imports it, and it is a policy-free system client (it sits in the guard's allowlist only for that reason).
- [ ] **human (via the lead):** accept the authorisation and sign-out changes in "Who sees what differently" (INV-3; security's verdict waits on this).
- [ ] **qa (WP-2c):** record the `/api/field` contract changes from the table under "Decision: `/api/field`": 404, 400, and formula with count 0.
- [ ] **lead:** the phase docs say "Alembic uses POSTGRES_DB_URI" (`phase-0-security-and-subtraction.md` 0c). That is wrong and should become "delete the unused variable".
- [ ] **qa (WP-2a):** regenerate golden case `policy_include_all_all_time` in `tests/golden` after unit 9 lands. **INV-2 note:** the recorded Druid request changes from `{"type": "and", "fields": [null, <policy>]}` to `<policy>` alone. This is an intended difference: a real Druid rejected the old request, so no user ever received results from it. Requests whose request filter is non-empty are unchanged, byte for byte, including `and`-shaped ones (pinned by `test_policy_is_anded_with_the_query_filter` and `test_an_and_query_filter_is_wrapped_not_mutated`). If any golden case was regenerated while `64dc60e` alone was on the branch, regenerate it again: that commit flattened `and` filters, and `a89c55d` restores the original shape. backend-2 did not edit `tests/golden`.
- [ ] **qa:** for WP-2b, add an authz case showing a non-superuser's `run_query` carries their policy filter.
- [x] **lead:** keep `/api/timeout` out of WP-0d. Done 2026-10-04.

## Log

- 2026-10-04 core-1: claimed the WP and merged `mig/decisions-0001-ownership` (decision 0001).
- 2026-10-04 core-1, units 1-4 tests (`20622b9`, `e6f51b5`, `be09dfe`): failing regression tests. Check: on the branch, 5 failed and 11 passed, each failure for its bug.
- 2026-10-04 core-1, interrogate: A on opus, B on fable, C on sonnet. Decision recorded above, and tests tightened (`978d61c`).
- 2026-10-04 core-1, unit 5 core part (`bd71d45`): deleted the unused `get_dimension_time_boundary`. Check: the module and `druid_context` import, black is clean, and no references remain.
- 2026-10-04 core-1, patches v2: proved in a scratch tree, which is branch head plus both patches. Check: `pytest tests/web tests/infra` gives 22 passed. App modules import. The pipeline import check passes with JWT blocked. `docker compose config` no longer emits `POSTGRES_DB_URI:`.
- 2026-10-04 backend-2: took over on `mig/WP-0c-pure-mistake-bugs-backend` (from `32dca82`, merged `mig/integration`). Status `building`.
- 2026-10-04 backend-2, units 2-5 (`638b9e4`, `68aa48d`, `ce12e99`, `0cc1c6a`, `abf1fa9`): applied `backend.patch` one fix per commit. Check: `pytest tests/web` 14 passed; the index matches the whole patch (`git apply -R --check --cached`); the claim decodes as `remember_me: true/false` from a real login response; `web.server.util.util`, `models.python.base` and `data.alerts.send_alert_notifications` import with `jwt` and `flask_jwt_extended` blocked. C-5 acknowledged.
- 2026-10-04 backend-2, unit 1: moved to WP-0b by the lead. Removed `tests/infra/test_compose_environment_names.py` and `WP-0c/infra.patch` from this branch; both stay recoverable from `32dca82`.
- 2026-10-04 backend-2, unit 6 (`a076b1a` test, `a010c1c` fix): `/api/timeout` now calls `unset_jwt_cookies` on the timeout response. Check: before the fix 1 failed and 3 passed (`assert 'accessKey' in set()`); after, `pytest tests/web` 18 passed.
- 2026-10-04 backend-2, unit 9 (lead request from WP-2a; `70ecd0e` test, `64dc60e` fix): null AND operand in the policy filter. Check: before the fix 2 failed (`fields: [None, ...]` and `AttributeError: 'NoneType' object has no attribute 'filter'`); after, `pytest tests/web` 21 passed. Golden regeneration is requested from qa (see Requests).
- 2026-10-04 backend-2, unit 7 red (`f99d24d`): `/api/field` tests. Check on the old view: 4 failed (restricted count, unknown id x2, cap), 2 parity cases passed.
- 2026-10-04 backend-2, unit 7 interrogate: A on opus, B on fable, C on sonnet (C via the lead). Synthesis and outcomes under "Decision: `/api/field`".
- 2026-10-04 backend-2, unit 9 follow-up (`3681cb7` red, `a89c55d` fix): `and_policy_filter` builds a new `and` instead of using pydruid's in-place `&`. Check: the new case failed with the flattened shape before the fix; 4 passed after.
- 2026-10-04 backend-2, unit 7 (`1a72037`): reworked after the interrogate. Check: on the pre-unit-7 view, the final tests give 6 failed and 2 passed. The restricted user got `42` (whole datasource) instead of `7`, and unknown ids raised `AttributeError` (a 500). After the fix, `pytest tests/web` gives 46 passed, the Flask app imports, and lint shows only `main`'s findings.
- 2026-10-04 backend-2, unit 8 (`34c7e7b`): structural guard. Check: the scanner reports 3 unallowlisted findings on the pre-unit-7 `field.py` and `api.py`, and 0 now; 13 cases pass. It catches aliases (`ctx = current_app.druid_context`).
- 2026-10-04 backend-2: status `review` at `60edb27`. Gates: qa approved; security blocked on human acceptance only; reviewer changes-requested.
- 2026-10-04 backend-2, review round 1 fixes:
  - `7ffdff4` deleted the applied `backend.patch`.
  - `b67ec9d` made the field summary a function, dropped ApiRouter's `fields_api`, and reads each formula once.
  - `cf91896` dashboard test through the registered route with the exact `Location`; it fails on the old `request.args` forwarding (evil.example host, dropped locale). Timeout test with the app's real `install_login_manager_signal_handlers`; it still fails without `unset_jwt_cookies`.
  - Merged core-1's `mig/WP-0c-pure-mistake-bugs-core` (`21a6d89`: `get_field_time_boundary` and its cache deleted) and the WP branch's verdict commits.
  - `59c55d3` red and `9158d00` fix: unit 10 (policy into `dimension_filter`; docstrings state the real invariant).
  - `ef790b0` capability-based guard over four trees, with `ALLOWLIST` and `KNOWN_VIOLATIONS`.
  - WP file: sign-out effect corrected; "Who sees what differently" table and release note added; `contracts_changed: [C-5]`; security lows recorded as open item 8.
  - Check: `pytest tests/web` gives 61 passed.
- 2026-10-04 core-1, review follow-up (branch `mig/WP-0c-pure-mistake-bugs-core`, from backend-2's `7ffdff4`): in `web/server/data/time_boundary.py`, deleted `DataTimeBoundary.get_field_time_boundary`, the `time_boundary_cache` and the `cache_key` path of `get_filtered_time_boundary`. Requested by interrogate A, B and C and the code reviewer. The only live caller (`views/field.py`) passes no key, and a `field__<id>` key would serve one user's policy-filtered dates to another. Check: a grep of `web`, `scripts`, `data`, `db`, `util`, `models` and `tests` finds no remaining reference (`tests/web/test_field_info_route.py` uses a real `DataTimeBoundary`, not a stub, so it needs no change). `pytest tests/web tests/infra` gives 46 passed. `ruff --select F`, black and mypy (`--disallow-untyped-defs`, module in isolation) are clean.

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

**backend-2, final branch head.** `PYTHONPATH=$PWD uv run --no-project -p 3.8 --with-requirements /tmp/reqs.txt --with 'pytest<8' python -m pytest tests/web -q` gives `61 passed` (review round 1; `46 passed` at `60edb27`). The files are `test_api_routes` 1, `test_authorized_query_client` 1, `test_dashboard_unauthorized_redirect` 4, `test_session_persistence` 8, `test_timeout_route` 4, `test_query_policy_filter` 8, `test_field_info_route` 9 and `test_no_raw_queries_from_routes` 26.
- `import web.server.app, web.server.routes.api, web.server.routes.views.field` succeeds with placeholder environment variables.
- `ruff check tests/web` is clean. `black -S -t py38` is clean on all new and changed test files and on `field.py`, `query_policy.py`, `authentication.py` and `dashboard.py`. `ruff --select F` and black on `api.py` and `template_renderer.py` report only what is already on `main` (F401 `ROOT_SITE_RESOURCE_ID`, F401 `get_configuration`, and black's tuple unpack in `import_self_serve`).
- Red-before-fix evidence for each unit is in the Log.

**Runtime `verify`: deferred to the QA harness.** The app needs Druid with data, which is not available here. Steps:
1. **Dashboard redirect.** Sign in as a user with no `view_resource` on a dashboard and open `/fr/dashboard/<name>?_external=1&_scheme=https://evil.example/x?`. Expect a 302 to `/fr/unauthorized` on the same host. Opening it signed out should give the login redirect.
2. **Remember me, then timeout.** Sign in with "Remember me" ticked, set the inactivity cookie to expire (or wait `ui.sessionTimeout`), and expect no redirect and `/api/timeout` returning `{"timeout": false}`. Sign in without it and expect `{"timeout": true}`, a `Set-Cookie: accessKey=; Expires=Thu, 01 Jan 1970`, a redirect to `/login?timeout=1`, and the next `GET /api/...` returning 401 (before the fix it returned data). Needs `AUTOMATIC_SIGN_OUT` on.
3. **`/api/field` as a restricted user.** Give a user a query policy for one district, open an indicator's About tab, and compare `GET /api/field/<id>` with an admin's: counts and dates match a district-filtered query, the formula is present, and the admin's numbers are unchanged before and after the restricted request (shared cache). Also check `GET /api/field/not_a_field` returns 404 and 21 ids return 400. Check one data-catalog-only field's About tab: no formula, as before.
4. **Queries for a restricted user with no request filter.** Run a query with no filters as a policy user and expect results, not a Druid error (unit 9).
- The golden and authz suites will judge INV-2 and INV-3 once they land (WP-2a, WP-2b). See the qa requests.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-04 qa-0c at 60edb27: all 8 units red on integration and green on the branch; 22 request-level probes through real routes and decorators (9 open-redirect payloads, timeout cookie clearing, /api/field restricted vs admin, 400 random filters through and_policy_filter byte-identical, pipeline import without JWT libs); 7 deliberate breakages all caught. Browser verify deferred to WP-2e. |
| reviewer | changes-requested | 2026-10-04 rev-0c at 60edb27 (three-model interrogate run): fixes correct, no policy leak found. Fix: WP misstates the sign-out effect (pre-deploy remember-me sessions and non-remembered users are now really signed out after 30 min idle; add a who-sees-what table for units 2,3,5,6,7,9; contracts_changed [C-5]); delete dead policy-blind get_field_time_boundary and cache (core); SEC-4 guard misses DruidQueryClient classmethod, direct lookup construction and other dirs; docstring 'every query carries the policy' false for ExactUniqueCount modify_query (latent); redirect test uses __wrapped__; stale backend.patch; lead: skill and phase-2 doc stale. |
| security | blocked | 2026-10-04 sec-0c at 60edb27: no high or medium findings; all seven rulings hold. Blocked only for HUMAN acceptance of the intended /api/field narrowing (INV-3/SEC-4); becomes approved with no code change once accepted. Low: /api/timeout has no CSRF (SEC-5/WP-5d); login set_cookie vs timeout unset_jwt_cookies settings may diverge (WP-5d helper); AST guard should scan web/server/util too. |
