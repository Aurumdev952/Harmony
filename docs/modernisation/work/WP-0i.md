---
wp: "0i"
title: "Guard the dashboard render and thumbnail routes"
status: review
owner_role: "backend"
instances:
  - name: "lead-1"
    files:
      - scripts/create_bot_accounts.sh
  - name: "backend-7"
    files:
      - web/server/routes/page_renderer.py
      - web/server/routes/views/page_renderer.py
      - web/server/routes/views/dashboard.py
      - web/server/routes/views/query_policy.py
      - web/server/configuration/bots.py
      - web/server/app.py
      - web/server/redis/thumbnail_storage_service.py
      - web/server/api/thumbnail_storage_models.py
      - web/server/security/signal_handlers.py
      - tests/web/render/**
      - tests/web/test_redis_password.py
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
6. **WP-2b check.** Run the WP-2b pure layer against the fix in a scratch copy, and ask qa-2b to flip the N1, N2 and N7 pins. **Done**; the request is open.
7. **Round-2 rework.** The render and email origin comes from `DEPLOYMENT_BASE_URL`, urlbox failures are logged redacted, the digest is canonical, and the slug lookup uses equality ignoring case. Check: `tests/web` green the CI way. **Done** (`10175ed`, `4e05bcb`, `76c31e2`).
8. **Round-3 rework.** Render URLs no longer include the request script root, `DEPLOYMENT_BASE_URL` is validated, and the Redis claim race is closed. The tests found missing in round 2 are added, and this file is brought up to date. Check: new tests red on `76c31e2` for the intended reason, `tests/web` green, lint gate clean, and the WP-2b pure layer run with the flipped file. **Done.**

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
  - The renderer now never takes a URL. It always builds this deployment's own dashboard URL with `deployment_dashboard_url`, and keeps only the locale and the `#h=` session hash from a client link (`dashboard_page_args`).
  - That URL is `deployment_origin(DEPLOYMENT_BASE_URL)` plus a path built from the URL map (`current_app.url_map.bind('').build`). Neither part comes from the request.
    - Round 1 used `url_for(..., _external=True)`, which takes the host from the request's `Host` header. The app sets no `SERVER_NAME`, `ProxyFix` or trusted hosts, so this was safe only behind nginx-proxy's unknown-host 503 (security round 1).
    - Round 2 used the configured origin plus `url_for`. That still prefixed the request's script root, and gunicorn 20.0.4 copies a `SCRIPT_NAME` request header into the WSGI environ. With `SCRIPT_NAME: @attacker.invalid`, the token was minted for `https://<origin>@attacker.invalid/...` (reviewer and security round 2).
  - `deployment_origin` accepts only a bare https origin: no userinfo, path, query or fragment, and a numeric port if any. The app refuses to start on any other value (`validate_deployment_base_url`, next to the JWT key check), and every render checks the origin again before it mints a token.
  - The same origin is used for the link in an emailed dashboard when the client sends no `dashboardUrl`. A client-sent `dashboardUrl` is still mailed as the link (carried risk 10).
- **Request args shaped a shared, cached thumbnail** (3 of 3): `width`, `delay`, `fail_if_selector_present` and `force`.
  - Thumbnails now ignore request args (`request_args={}`), and `force` is no longer overridable anywhere.
  - The old `request_args` bug, which assigned the whole dict to every param, is fixed.
  - Only a 200 render is cached.
- **Anonymous callers could reach retrieve** (3 of 3). Under public access, an anonymous request with a `Referer` header passed Potion's decorator. Retrieve now uses `force_authentication=True`.
- **The fingerprint must describe the policy the render actually runs under** (Fable and Sonnet; Opus raised it as drift).
  - For header-auth (`X-Username`) callers, the request identity holds raw account needs. The render token re-derives them through `_compute_token_query_needs(['*'])`, which splits complex needs per dimension and drops non-authorisable dimensions.
  - The fingerprint now digests `render_token_query_needs()`: the same derivation, run on the request identity. Superusers digest to `"superuser"`.
  - The render token's `query_needs` and the fingerprint now share the constant `RENDER_TOKEN_QUERY_NEEDS`.
- **Slugs are editable and reusable** (Fable; Opus and Sonnet flagged the key format). The key is `thumbnail:v2:<resource_id>:<sha256>`.
  - The lookup is equality ignoring case (`lower(slug) = lower(:slug)`), not ILIKE, so `%` and `_` are not wildcards. Probing with `%` and `_` therefore no longer reveals slugs; a signed-in caller can still tell an existing slug (403) from a missing one (404), as on base and on the dashboard page itself. `get_dashboard` is shared, so the dashboard page (`routes/dashboard.py:30`) and the embedded query page (`embedded_query.py:121`) change the same way.
- **PENDING could stick after a failure, and two callers could both claim a render** (3 of 3). The claim now uses `cache.add` (SETNX on Redis), and a `finally` deletes the claim unless a 200 render was stored.
  - The claim loop gives up after `PENDING_STATE_TIMEOUT`.
  - When `add` fails and `get` misses, the loop deletes the stale entry only on a FileSystemCache. That backend keeps expired entries on disk, so `add` keeps failing on them. On Redis the same miss means the holder has just released its claim, and another caller may already hold a new one, which a delete would destroy. Two renders could then run at once (round 2, fixed in round 3).
- **Secrets in logs** (Sonnet). On any non-200, urlbox failures logged `res.url`, which carries the urlbox API key and the minted JWT (INV-6). The log line now names only the format, the dashboard path and the status.
  - A `requests` exception, such as a refused connection, is caught and logged as one line naming the exception class only (security round 1).
  - Tests cover a closed port and a 500 whose response URL carries the key and the token.
- **The digest must not depend on set order** (QA and reviewer, round 1). It is taken over the sorted per-dimension maps the Druid filter is built from (`canonical_policy`). It is identical in fresh interpreters under different `PYTHONHASHSEED` values (test).

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

## INV-1 note: renders and email links depend on `DEPLOYMENT_BASE_URL`

- **No fallback.** Renders and emailed dashboard links use the configured `general.DEPLOYMENT_BASE_URL` only, never the request's `Host` or script root.
  - A deployment whose value is stale renders the old host's page, and emails link to it. A moved domain, or a value copied from the template, is stale in this sense.
  - The render fails if urlbox cannot load that host. If someone else controls the host, the minted token goes to them.
- **Checked values in the repo.**
  - `config/harmony_demo/general.py:19` is `https://harmony_demo.zenysis.com`. That is not the host the local or demo stack is served on, so renders from those stacks point at that host.
  - `config/template/general.py:19` is a placeholder.
  - Both pass the new startup check.
- **Startup check.** Under gunicorn (or the reloader), the app now refuses to start when `DEPLOYMENT_BASE_URL` is not a bare https origin.
  - It refuses plain http, userinfo, a path prefix, a query, a fragment and a non-numeric port.
  - A deployment served over http, or under a path, must change its value before this ships. That is for the human, per deployment.
- **Sharp edge** (security round 2, F4). A staging host that reuses a production config sends its render tokens and email links to production.
  - With different JWT secrets, the renders fail, but the staging tokens still reach production's access logs.
  - With the same secret, production data is rendered for a staging user.
  - Staging must set its own `DEPLOYMENT_BASE_URL`.
- **Ordering.** WP-0i must not ship ahead of WP-0b (security round 1).
- **Carried to WP-1h.** The self-hosted renderer should take the same configured canonical origin from settings, or better, render without a public URL at all.

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
| Any caller who may render | `width`, `delay`, `fail_if_selector_present` or any other render arg on `/png/thumbnail` or retrieve | **shaped the thumbnail that is cached and shared with other viewers for 14 days** | ignored (`request_args={}`); `/pdf` and `/jpeg` still accept the listed args |
| Any caller who may render, reaching gunicorn directly | a spoofed `Host` header, or a `SCRIPT_NAME` header such as `@attacker.invalid` | **the render URL's host came from the request, so the minted token went to the caller's host** | ignored: always `DEPLOYMENT_BASE_URL` plus a path from the URL map |
| Anyone who can view the dashboard | `share_via_email` with `dashboardUrl` | **the token minted for each recipient (admins included) is sent to any URL** | renders always load this deployment's dashboard page on `DEPLOYMENT_BASE_URL`; only the locale and `#h=` hash are taken from the link. The mailed link is still the client's `dashboardUrl` (carried risk 10). |
| Signed in | retrieve, unknown `key` or no `key` | 500 (the handler dereferenced a missing dashboard) | 404, no render |
| Anonymous | retrieve, unknown `key` or no `key` | 401; under public access with a `Referer`, 500 | 401 |
| Signed in, with `view_resource` | retrieve or any render route, the slug in another case (`MALARIA-OVERVIEW`) | 500 (case-sensitive lookup) | 200, rendered as the caller (retrieve: from the caller's policy cache entry) |
| Signed in, no `view_resource` | the same, slug in another case | 500 | 403, no render |
| Anonymous | the same, slug in another case | 500 on every render route (the case-sensitive lookup fails before the check); retrieve as above | 401 |
| Signed in | retrieve or any render route, a slug containing `%` or `_` that matches no slug exactly | 500 | 404 (or 403/200 when it equals a real slug ignoring case) |
| Signed in | the dashboard page `/dashboard/<slug>` (`routes/dashboard.py:30`) or the embedded query page (`embedded_query.py:121`) with `%` or `_` in the slug | **ILIKE pattern: `/dashboard/malaria%` served the first matching dashboard, or the unauthorised redirect, which revealed that it exists** | 404 page unless the slug equals a real one ignoring case |
| Admin | the Admin user list | `renderbot@zenysis.com` hidden (in `BOT_USERS`) | listed, so admins can see and deactivate the leftover site-admin account |
| Embedded and screenshot modes | `/dashboard/<slug>?screenshot=1`, iframe mode | page flags on the dashboard page, which checks access itself | unchanged (these do not go through the render routes) |

No other decision moved. The WP-2b pure layer is identical outside the render pins (see Evidence).

## Carried risks (for WP-1h unless noted)

1. **Existing render-bot accounts, created by the old script, are still site admins in deployments.**
   - The old `scripts/create_bot_accounts.sh` created `renderbot@zenysis.com` with `-a`. The lead removed that line on this branch (`e6a90bf`), so new stacks create no render bot. The remaining `--automation_user` line is pre-existing and stays a lead item.
   - No server path mints a token for an existing account any more (`grep RENDERBOT web` is empty), so each one is an unused admin login. It now shows in the Admin user list.
   - Deactivating or demoting those accounts is an operation on real data, so it is for the human (Questions).
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
9. **A token with narrowed `query_needs` digests the narrow policy, but its render runs over the whole account** (security F3).
   - The caller's digest comes from the token's narrowed needs. The render token (`query_needs: ['*']`) is re-resolved against the whole account.
   - No server path issues such a token today, so this is unreachable. It is pinned by a strict xfail (`test_narrowed_token_caller_digest_matches_their_render`).
   - The cheap fix, for WP-1h or WP-5d: use a per-user key whenever the caller's token `query_needs` is not `['*']`.
10. **`share_via_email` still mails the client's free-form `dashboardUrl` as the link** (security F5; QA and the reviewer noted it outside the diff).
    - No token goes to it any more; renders ignore it.
    - It is still a phishing channel from a trusted sender. Build the link from the slug with `deployment_dashboard_url`.
    - Carried to WP-0k, which takes over request-derived links.
11. **gunicorn 20.0.4 copies a `SCRIPT_NAME` request header into the WSGI environ.**
    - The render paths no longer read the script root.
    - Any other `url_for(_external=True)` or `request.script_root` use is still exposed to callers who reach gunicorn directly. nginx drops headers with underscores by default.
    - Upgrade requested from infra (WP-3b).
12. **A truncated urlbox body is cached for 14 days.** A 200 with a short body is stored as the thumbnail. WP-1h should check `Content-Length`, or the PNG signature and `IEND`, before caching.
13. **The FileSystemCache backend** (development only) can still let two callers render at once: one caller's stale-entry delete can race another's claim. Redis, the production backend, has no delete on that path.
14. **`response_wrapper` treats only a 500 from urlbox as a failure.** A 4xx error body would be streamed as `application/pdf` or `image/*`. This is pre-existing.

## Questions for the human

- **Existing render-bot accounts.** Deployments set up before this WP have a `renderbot@zenysis.com` site-admin account, created by the old `scripts/create_bot_accounts.sh` (`-a`; the line is gone since `e6a90bf`). No code path signs in as it any more, and it now shows in the Admin user list. Should these existing accounts be deactivated, or demoted from site admin, on each deployment? That is an operation on production data.
- **`DEPLOYMENT_BASE_URL` per deployment.** Before this ships, each deployment's value must be its real public https origin, or the app will not start (see the INV-1 note).

- **Public PDF download.**
  - Decision 0004 requires an authenticated caller on every render route.
  - On deployments with public access enabled, anonymous visitors therefore lose PDF download. JPEG already failed with a 500.
  - The PDF they got was not wider than the public page, but producing it needed a site-admin token.
  - The choice: accept the loss (this branch plus the frontend request below), or keep public PDF through a dedicated non-admin public render account as a follow-up?

## Contract changes

These are WP-2c API contract recordings (`tests/contract`, owned by qa), not one of C-1 to C-11.

- **`storage.retrieve.cached`** (`GET /api2/storage/retrieve?key=contract-dashboard`).
  - Old: `seed_cache.py` writes `thumbnail_contract-dashboard` into Redis before any case runs. The case reads it and returns 200 with the seeded base64 PNG.
  - New: the legacy key is never read. The key is now `thumbnail:v2:<resource_id>:<policy digest>`, and the digest depends on the caller. The case misses and renders through urlbox, which the stack cannot reach, then returns 200 with an empty string `""` and no `PENDING` marker. The recorded shape (`type: string`, status 200) still holds; the value changes.
  - Migration for WP-2c: drop `seed_cache.py`, or stop relying on it. No PENDING stall is left to avoid. Rename or annotate the case as "miss with the renderer unreachable".
- **`storage.retrieve.unknown_slug`** (`key=contract-no-such-dashboard`).
  - Old: 500 (finding F11).
  - New: 404, from werkzeug `NotFound` inside a Potion route, so the error body shape changes too. Re-record the body.
- **Consumers.** qa-2c (the recordings and the replay). Frontend callers already treat an empty string as "no thumbnail" (`ThumbnailStorageService.js:25`, `Overview/index.jsx`).
- **Acknowledgements.**
  - [x] qa-2c: accepted both changes (qa-3, 2026-10-05, `WP-2c.md` on `mig/WP-2c-api-contract-recordings` at `bf08a36`). Whichever of WP-0i and WP-2c merges second re-records both cases, and replaces the start-up seed in `seed_cache.py` with a v2-key seed after `dashboard.create`.

## Requests

- [ ] **qa (qa-2b): flip the N1, N2 and N7 pins** in `tests/authz/test_render_routes.py` on this branch.
  - The front matter will need a qa instance (for example `qa-2b`) with `files: [tests/authz/test_render_routes.py]`, so that `task_gate` attributes that file to qa.
  - The overlay is 3.8-safe: it uses `contextlib.ExitStack`, not a parenthesised `with`, and passes `ci/check_py38_syntax.py`.
  - A verified flipped version is at `docs/modernisation/work/WP-0i-evidence/test_render_routes.flipped.py`. It passes 18 of 18. The full pure layer gives 4681 passed against 4675 on base, and the non-render outcomes are identical (Evidence).
  - N7 is flipped, not dropped: `test_caller_chosen_url_does_not_receive_the_minted_render_token`. With `?url=https://attacker.invalid/steal&cookie=accessKey=planted` on `/png/thumbnail`, `/pdf` and retrieve, the urlbox call loads `<DEPLOYMENT_BASE_URL>/dashboard/<slug>?...`, and the token belongs to the caller.
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
- [x] **lead:** remove the render-bot line from `scripts/create_bot_accounts.sh:5`. Done on this branch (`e6a90bf`, instance `lead-1`). Whether to deactivate the existing accounts is a human question (above).
- [x] **core:** remove the unused `RENDERBOT_EMAIL` from `config/settings.py:39`. This is done on WP-1h's core branch.
- [ ] **infra:** remove `RENDERBOT_EMAIL` from `docker-compose.yaml:145` and `:179` (`:143` and `:178` on WP-1h's core branch).
- [ ] **infra (WP-3b):** upgrade gunicorn from 20.0.4 (`uv.lock`), so that a `SCRIPT_NAME` request header no longer reaches the WSGI environ (carried risk 11). Not blocking: the render paths no longer read it.
- [x] **qa (qa-2c):** acknowledge the two contract changes above (done at `bf08a36`). The `seed_cache.py` rework belongs to whichever of WP-0i and WP-2c merges second.
- [ ] **human:** remove `RENDERBOT_EMAIL` from `.env.example` (a human item; agents do not read `.env*`).
- [ ] **human:** accept the INV-3 table, including the public-PDF row, and answer the questions above.

## Log

- 2026-10-04 backend-7 unit 1: `pstack:how` on the render routes, token minting, the thumbnail cache and the page check; N7 found. Check: findings recorded above.
- 2026-10-04 backend-7 unit 2: 61 tests in `tests/web`, with urlbox mocked. Check: `uv run pytest tests/web` gave 43 failed and 18 passed on base `3780c8c` (`0c604a3`).
- 2026-10-04 backend-7 unit 3: the guard, the per-policy thumbnail cache, own-origin renders, no caller `url`/`cookie`/`force`, and a redacted log; the design changed after interrogate. Check: 67 passed on the branch; the same 67 tests against the base code gave 48 failed and 19 passed (`9528b22`).
- 2026-10-04 backend-7 unit 4: no render-bot token is minted, and the test env no longer sets `RENDERBOT_EMAIL`. Check: 67 passed; `grep RENDERBOT web` finds nothing (`8962db2`).
- 2026-10-04 backend-7: moved the render tests to `tests/web/render` and merged `mig/integration` (`b42a7be`). Check: `uv run pytest tests/web` gave 135 passed and 1 failed. The failure is `test_graphql_endpoint_removed` (`ModuleNotFoundError: flask_migrate`), and it fails the same way on integration.
- 2026-10-04 backend-7: the render tests now serve a `ThumbnailStorageResource` subclass, because other `tests/web` suites register the production class on their own `Api`. Check: on the web server's stack (Python 3.8, `requirements*.txt`, the same rewrite as `tests/authz/run.sh`), the whole `tests/web` tree gives 136 passed.
- 2026-10-04 backend-7 units 5-6: the INV-3 table, and the WP-2b pure layer (`24e9e88`) in scratch copies. Check: base 4672 passed; the branch with today's pins 4662 passed plus 10 render-pin errors (they patch symbols this WP removed); the branch with flipped pins 4677 passed.
- 2026-10-04 backend-7 round 2: the test app now runs without `SERVER_NAME` and adds a cookie login path through the real `signal_handlers.on_identity_loaded`; patches fail when their target is gone (`10175ed`). Check: lands with the next commit, whose expectations it serves.
- 2026-10-04 backend-7 round 2: renders and email links use `DEPLOYMENT_BASE_URL`; `requests` failures are logged redacted; the claim loop is bounded; the digest is canonical; slug equality ignores case; renderbot leaves `BOT_USERS` (`4e05bcb`). Check: `tests/web` green the CI way, and the new tests fail on the round-1 head for their reasons.
- 2026-10-04 backend-7 round 2: merged `mig/integration` `8638861` (`f2be31d`); made the flipped overlay pass the lint gate (`76c31e2`). Check: the lint gate is clean; QA measured 195 passed plus 1 strict xfail in `tests/web`.
- 2026-10-05 backend-7 round 3: render and email URLs built from the URL map on a validated `DEPLOYMENT_BASE_URL`, checked at startup (`cb67bed`). Check: the 32 new origin tests fail on `76c31e2` (the hostile `SCRIPT_NAME` gives `https://harmony.tests.invalid@attacker.invalid/...`) and pass on the head.
- 2026-10-05 backend-7 round 3: the Redis claim race is closed, and tests are added for thumbnail args, redaction of a 500, the hash seed and the bounded claim loop (`03acb20`). Check: each new test kills its mutant (dropping `request_args={}`, logging `res.url`, an unsorted canonical policy, no deadline, an unconditional delete). `tests/web` 237 passed plus 1 strict xfail; the lint gate is clean.
- 2026-10-05 backend-7 round 3: flipped N7 in the WP-2b overlay, and brought this file up to date (INV-1 note, INV-3 rows, contract changes, risks, requests, evidence). Check: the WP-2b pure layer is 4681 passed with the overlay, 4675 on base, and 4663 plus 12 errors with today's pins; the non-render outcomes are identical to base.
- 2026-10-05 backend-7 round-3 rework: merged `mig/integration` `61db9f8` (`fc3d8de`: py38 ruff target, 3.8 syntax guard, gate fix for lead-owned paths). Check: the 3.8 syntax guard passes 852 files.
- 2026-10-05 backend-7 round-3 rework: the render fakes are now `render_fakes.py`, imported by basename. A new test checks that a gunicorn `create_app` refuses a hostile `DEPLOYMENT_BASE_URL` before any database access (`d5c3d23`). Check: tests/web gives 238 passed and 1 xfail on 3.9 (CI way) and on 3.8 (requirements*.txt). With a regular `tests` package placed after the repo on the 3.8 path, as the editable Flask-Potion install does, the round-3 head fails collection (`flask_testing`) and this head passes. The startup test fails ("the database was touched") when `validate_deployment_base_url` is removed.
- 2026-10-05 backend-7 round-3 rework: the overlay now uses `ExitStack` instead of a parenthesised `with`. Stale lead, render-bot and qa-2c items updated, with the evidence refreshed. Check: the old overlay fails the 3.8 guard at line 159 and the new one passes. The lint gate is clean. The WP-2b pure layer (`7933e17`) is 4681 passed with the overlay against 4675 on base, with identical non-render outcomes.

## Evidence

Round-3 rework head, after merging `mig/integration` `61db9f8`. Commands are run from the repo root.

- **`tests/web`, run the CI way.** `uv run --locked pytest -m 'not stack' -- tests/web` (as `ci/pytest_suites.sh` does) gives 238 passed and 1 xfailed. The xfail is the strict pin for carried risk 9.
  - `tests/web/render` alone gives 143 passed and 1 xfailed.
  - `docs/modernisation/work/WP-0i-evidence/tests-web-render.txt` lists every case by name.
- **`tests/web` on the web image's stack.** CPython 3.8.20 with `requirements.txt` and `requirements-web.txt`, using the WP-0c rewrite of the `-e git+` lines, gives 238 passed and 1 xfailed.
  - That rewrite installs Flask-Potion from git, not as an editable checkout, so it does not ship the checkout's `tests` package.
  - To reproduce QA's environment, a regular `tests` package that imports `flask_testing` is put after the repo on `PYTHONPATH`.
  - With it, the round-3 head (`cc01fa0`) fails collection with `ModuleNotFoundError: flask_testing`, and this head gives 238 passed and 1 xfailed.
- **3.8 syntax.** `uv run --no-project -p cpython-3.8.20 python ci/check_py38_syntax.py config data db log models graphql util web scripts tests/web` gives 852 files checked and 0 problems.
  - The same check on `WP-0i-evidence/` gives 0 problems.
  - The previous overlay failed it at line 159: a parenthesised `with`.
- **Fail before.**
  - **Against `mig/integration` code.** The round-3 `tests/web/render` suite was run against the `mig/integration` tree (`1697a7a`) with `--continue-on-collection-errors`. It gave 126 failed, 5 passed and 1 collection error.
    - The collection error is `test_thumbnail_policy_digest.py`: `query_policy_fingerprint` does not exist on base.
    - 68 of the failures are `KeyError: 'sqlalchemy'`. The base handlers use `Transaction` and `find_one_by_fields` directly, and the harness does not fake those, so these failures do not test the defect.
    - The rest fail on the defect itself: 401 or 500 where a refusal or a render is expected, the bot identity, the slug-only key, caller args reaching urlbox, an unredacted URL, a request-derived origin, and missing `deployment_origin`.
    - Five cases pass on base: the three `test_slug_matches_in_any_case` cases, the anonymous retrieve refusal, and `test_render_with_an_unusable_configured_origin_makes_no_outbound_call`. The last passes only because base fails earlier.
  - **Against the round-2 head `76c31e2`.** The 32 new origin tests fail there:
    - 12 `SCRIPT_NAME` cases, because the render or link host is the attacker's;
    - 20 that need `deployment_origin` or `validate_deployment_base_url`.
    - The 8 hostile-`Host` tests pass there.
  - **The claim-race test** fails on `76c31e2` code: the caller deleted the third caller's claim and rendered again.
  - **Mutants.** Each new test fails under its mutant, and none hangs:
    - dropping `request_args={}` from thumbnails fails 2 tests;
    - logging `res.url` on a non-200 fails 3 tests;
    - an unsorted `include` in `canonical_policy` fails the hash-seed test;
    - removing the claim deadline makes the bounded-loop test fail with "the claim loop is spinning";
    - removing `validate_deployment_base_url(app)` from `_create_app_internal` makes the gunicorn startup test fail with "the database was touched before the origin check".
- **WP-2b pure layer.** `tests/authz/run.sh` from `mig/WP-2b-authz-suite` (`7933e17`; it changes nothing outside `tests/authz`) was run in scratch copies under `/tmp/wp0i-r3`, which were never committed.

  | Tree | Result |
  |---|---|
  | `mig/integration` `61db9f8` + WP-2b | 4675 passed, 580 skipped |
  | this head + WP-2b, with `WP-0i-evidence/test_render_routes.flipped.py` | 4681 passed, 580 skipped. The 18 render cases include 3 flipped N7 cases. |
  | round-3 head `03acb20` + WP-2b `09a7581`, with the pins as they are today | 4663 passed, 580 skipped, 12 errors. Each erroring pin patches `page_renderer.Transaction`, which this WP removed. |

  With `test_render_routes.py` deselected, the per-test outcome lists of base and head are byte-identical: 4663 passed.
- **Lint.** `ci/lint_python.sh mig/integration` reports "All checks passed!" and "18 files already formatted". That covers ruff E4, E7, E9, F and S at the py38 target, plus `ruff format --check`, on every Python file this branch changes, including the flipped overlay.
- **Imports.** `web.server.app` imports `deployment_origin` from `web.server.routes.views.page_renderer`. The startup tests import `web.server.app` in-process, and one of them runs `create_app` as gunicorn.
- **Not run: a live render.** urlbox is never called (decision 0004).
  - QA's round-3 live run on a fresh stack under gunicorn covered hostile `Host` and `SCRIPT_NAME` values. It also confirmed that a bad `DEPLOYMENT_BASE_URL` exits the container with code 1.
  - In-process, the `SCRIPT_NAME` path is measured with `environ_overrides`. That is what gunicorn 20.0.4 produces from the header.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-05 qa-0i round 4 at b5248bf: integration 61db9f8 already in the branch; no production file changed since e6a90bf so the round-3 live pass stands; lint gate whole-tree and 18 files clean; 3.8 guard 852 files 0 problems (round-3 overlay fails it, the ExitStack overlay passes); ci/pytest_suites.sh 8 suites green (web 238 plus 1 xfail); tests/web 238 on the 3.8 env with and without a shadowing tests package (round-3 head fails collection); WP-2b pure layer 4681 with the overlay, 4663 plus 12 errors with today's pins, all 5243 non-render outcomes identical to base; three mutants of the startup validation each fail the new gunicorn test; task_gate reports only status and verdicts; stale text and the INV-3 row corrected; qa-2c acknowledgement present in WP-2c at bf08a36. Info: the 3.8 syntax guard does not scan tests/authz or docs, add tests/authz when WP-2b merges (infra); a backend memory note overstates the editable-install shadowing (only a pip develop install shadows; uv --with-editable does not). |
| reviewer | approved | 2026-10-05 rev-0i round 4 at b5248bf: all four round-3 items closed (ExitStack overlay passes the 3.8 guard and 18 of 18 on WP-2b 7933e17 with 4681 pure-layer passes; task_gate reports only status and verdicts with integration's gate fix in the branch; stale text fixed; the gunicorn create_app startup test fails under three mutants); lint gate whole-tree clean with 18 files formatted; 3.8 guard 852 files 0 problems; tests/web 238 passed 1 xfail on the CI lane in both orders and on CPython 3.8 with and without a real Flask-Potion tests package shadowing the namespace (round-3 head fails collection, this head passes). No findings. Merge waits on the qa verdict, the qa-2b flip of the overlay in tests/authz and the human's INV-3 acceptance incl. the public-PDF row. |
| security | approved | 2026-10-05 sec-0i round 3 at e6a90bf: F2 closed (real gunicorn 20.0.4 with a raw SCRIPT_NAME header: 13 of 13 render at the configured origin on head, 9 of 13 leaked on the round-2 head; in-process 510 route and 600 email cases with 30 Host, forwarding and SCRIPT_NAME variants, 0 off-origin); F4 closed (43 hostile DEPLOYMENT_BASE_URL values refused incl. userinfo with escapes and newlines; the real gunicorn entry point exits 1 before binding on a bad value; odd accepted forms fail closed); INV-6 closed-port probe 13 of 13 clean in both formats; INV-3 matrix of 880 cases identical to round 2 and every base-to-head change matches a row after two documentation corrections applied by the lead (anonymous differently cased slug was 500 on every render route; the 403 vs 404 sentence narrowed to percent and underscore probing); claim deletion limited to FileSystemCache and Redis never deletes another caller's claim; semgrep F2 rule fires on round 2 and not on head; ownership clean bar the lead's own commit (claimed by a lead-1 instance). F3 and F5 carried as risks 9 and 10; O1 and O2 stay with WP-0k. Human must accept the INV-3 table incl. the public PDF loss before merge. |
