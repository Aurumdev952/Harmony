---
wp: "0k"
title: "Build outgoing links from the configured origin; match usernames exactly"
status: building
owner_role: "backend"
instances:
  - name: "backend-0k"
    files:
      - web/server/util/deployment_links.py
      - web/server/security/usernames.py
      - web/server/app.py
      - web/server/routes/views/page_renderer.py
      - web/server/routes/views/admin.py
      - web/server/routes/views/invite.py
      - web/server/routes/views/dashboard.py
      - web/server/routes/views/users.py
      - web/server/routes/views/resource.py
      - web/server/api/permission_api_models.py
      - web/server/api/dashboard_api_models.py
      - web/server/api/share_analysis_api_models.py
      - web/server/api/authentication_api_models.py
      - web/server/api/user_api_models.py
      - web/server/util/authentication.py
      - web/server/util/emails.py
      - web/server/security/signal_handlers.py
      - web/server/database/setup.py
      - tests/web/links/**
      - tests/web/usernames/**
      - tests/web/render/test_render_origin.py
      - tests/web/test_timeout_route.py
      - tests/web/test_session_persistence.py
      - tests/web/render/test_render_route_guards.py
      - docs/modernisation/work/WP-0k.md
      - docs/modernisation/work/WP-0k-evidence/**
      - .claude/agent-memory/harmony-backend-engineer/**
branch: "mig/WP-0k-configured-links-exact-usernames"
requirements: []          # decision 0006 names no SEC row; INV-1 and INV-3 apply
contracts_consumed: [C-5]
contracts_changed: []
security_review: true
---

# WP-0k: Build outgoing links from the configured origin; match usernames exactly

Decision 0006, phase 0 section 0k. Branched from `mig/WP-0i-render-route-guards` (WP-0i introduced the configured-origin helper in `web/server/routes/views/page_renderer.py`), with `mig/integration` 1697a7a merged.

## Plan

Each unit starts with a failing test.

1. **Does nginx-proxy 1.11.6 forward the raw Host?** On a local copy of the WP-2c stack (`tests/contract/stack` at b6e49b8) with `nginxproxy/nginx-proxy:1.11.6-alpine` in front of `web` as in `docker-compose.yaml`, send `forgot_password` with `Host: attacker.invalid` and `Host: real.org:@attacker.invalid`, over HTTP and HTTPS, and read the link mailpit receives. Check: evidence file with the requests, the Host the app saw and the mailed link.
2. **Every mailed or returned link comes from `DEPLOYMENT_BASE_URL`.** One helper builds an absolute URL for an endpoint on the configured origin with `url_map.bind('')`, never the request Host or `SCRIPT_NAME`. Callers: reset link (`admin.py`), invite link (`invite.py`), access-granted email (`permission_api_models.py`), new-dashboard email (`dashboard_api_models.py`), and any other `_external=True` or Host-derived URL. Check: tests with a forged Host and `environ_overrides={'SCRIPT_NAME': ...}` fail on the base and pass here.
3. **`send_email` links to the dashboard's own page.** The caller's free-form `dashboardUrl` contributes only the locale and the `#h=` session hash, as for renders. Check: tests with hostile `dashboardUrl` values.
4. **Usernames match exactly, ignoring case.** JWT login, flask-user's `find_user_by_username`, registration, invitation and role assignment compare `lower(username)` for equality, never a pattern. The JWT identity is `user.username`. Check: the look-alike case (`john_doe` for `john.doe`) fails on the base and passes here; an existing mixed-case login still works.
5. **Interrogate units 2 to 4 and fix what it finds** (f701e1c).
6. **Bind tokens to their account; prefer active accounts; refuse case-equal renames** (lead additions a and c, WP-0j security C2; 129125d). A session carries the account id (`user_id` claim), an API token is checked against its row's `user_id`; sign-in prefers an active account over a pending or deactivated one equal ignoring case; flask-user's change-username page and `PATCH /api2/user/<id>` refuse a username equal ignoring case to another account's. Check: token-binding and rename tests fail on f701e1c and pass after.
7. **Tokens with no account id sign in only an account created no later than they were issued** (lead addition a, the INV-3 decision for already-issued tokens). A session minted before WP-0k, or a render token, is refused when its `iat` is earlier, to the second, than the account's `created`. Check: the recreate case fails on 129125d and passes after; same-second, no-`created` and rename-residual cases pinned. Round 2 (lead, from a commit security review of 370f756): the database compares `iat` with `created`, so both are on the clock that wrote `created`; check on a throwaway Postgres with the database zone at UTC, +02:00 and -05:00.
8. **The API token check reads the row on every request** (lead addition a: the validity cache must not outlive a user delete). Check: a token used before its user is deleted and recreated under the same id (SQLite id reuse) signs in on 7's head and is refused after.
9. **Look-alike renames on both paths reach only the renamed account** (WP-0j security C1). Check: `PATCH /api2/user/<id>` and `/user/change-username` renames to `j_hn.doe` (pattern-matches `john.doe`) sign in only the renamed account, failing with `web/server` at 3f41aa0 and passing after.
10. **Merge WP-0i's head and `mig/integration`; trial merge with WP-0j and its harness.** Check: `tests/web`, `ci/lint_python.sh`, `ci/check_py38_syntax.py`, `uv run --locked mypy`, and `tests/privilege_escalation` on a scratch merge with `mig/WP-0j-rename-reset-guard`.
11. **INV-3 table, human acceptance list, requests (qa flips WP-2b T1 and T2), carried risks, merge-together rule.** Then `status: review`.

## Contract changes

**C-5, additive.** I own C-5.
- Old: a session JWT's `user_claims` are `needs`, `query_needs` and `remember_me`, and `identity` is the username as typed. API tokens add `id` (their `api_token` row). Render tokens carry narrowed `needs`.
- New: a session's `user_claims` also carry `user_id`, the account id, and `identity` is the stored `user.username`. API and render tokens keep their layout.
- Rules every reader of C-5 must enforce:
  - a token with `user_claims.id` signs in only the account its `api_token` row names, read on every request;
  - a token with `user_id` signs in only that account;
  - a token with neither signs in the account its `identity` names only if that account's `created` is not after the token's `iat` second, compared on the database's clock.
- Consumers: the Flask login loader (this WP). No other reader exists today. The FastAPI `PrincipalDep` (WP-5a and later) must port all three rules. Cookies issued before WP-0k stay valid under the third rule, so nothing is reissued.

## Merging with WP-0j

**WP-0j and WP-0k merge together, in one step, on one stack.**
- WP-0j guards renames of higher-privileged accounts, but still lets a caller rename itself or a lesser account to a username that pattern-matches an administrator's (WP-0j security C1). Only WP-0k's exact matching makes that harmless.
- WP-0k without WP-0j leaves the H5 rename-then-reset takeover open.
- WP-0k contains WP-0i's head (3b14989), so WP-0i lands first or with them.

The trial merge (unit 10) of `mig/WP-0j-rename-reset-guard` 19b9f62 into this branch has four conflicts:
- `web/server/api/user_api_models.py` and `permission_api_models.py`: imports only; keep both sides. In `update_user`, keep WP-0k's `username_taken` check first, before WP-0j's `can_update_item` and `verify_may_rename`. Its 400 reveals only that a username exists, which `GET /api2/user` shows any signed-in user, and neither refusal writes anything.
- `web/server/routes/views/users.py`: take WP-0j's `APIToken.is_revoked.is_(False)` line. WP-0k's removal of the token memo merges cleanly.
- The backend memory index: keep both lines.

`tests/privilege_escalation` then needs the three edits in `WP-0k-evidence/merge-with-0j/privilege_escalation.patch`:
- the mailer stub patches `admin.deployment_url` instead of `admin.url_for`, as WP-0j predicted;
- the harness passes the `User` to `create_user_access_token`, which now takes the account, not a username (two helpers and the `make_user` fixture).

With them the harness gives 122 passed and `tests/web` 405 passed. `conflicted-files-vs-0j.diff` is the resolved diff of the three conflicted Python files against WP-0j.

## INV-3 difference table

Rows L are links (units 2, 3, 5), U usernames (units 4, 6), T tokens (units 6 to 8). Every other request answers as before.

| # | Principal | Request | Before | After |
|---|---|---|---|---|
| L-1 | anyone, anonymous | `POST /api2/authentication/forgot_password`, and the admin `POST /api2/user/<id>/reset_password` that calls the same function, with a forged `Host` or `SCRIPT_NAME`, or behind TLS termination | the mailed reset link takes the request's scheme, host and script root | the link is on `DEPLOYMENT_BASE_URL`, https. Behind the stock nginx-proxy only a served host ever reached the app (unit 1), so there the visible change is `https://` instead of `http://` |
| L-2 | a caller allowed to invite | `POST /api2/user/invite` | invite link on the request host | on the configured origin |
| L-3 | a caller granting dashboard roles | access-granted email | link on the request host, to `/dashboard/<resource name>` | on the configured origin, to `/dashboard/<slug>?source=…`. A dashboard with no slug mails nothing and logs a warning; the role change is still committed |
| L-4 | a dashboard creator | new-dashboard email | request host | configured origin, `?source=` before any fragment |
| L-5 | a signed-in user sharing by email | `POST /api2/dashboard/<id>/share_via_email` (`dashboardUrl`), `POST /api2/share/email` (`queryUrl`) | the caller's free-form URL is mailed as the link | the dashboard's page, or the Advanced Query page, on the configured origin, taking from the caller's link only a locale Harmony has and the last well-formed `#h=` hash. An unparseable link gives the plain page |
| U-1 | anyone signing in: JWT login, registration, `X-Username` and `X-Password`, flask-user pages, role assignment by username, invitations, `forgot_password` | a username containing `_` or `%`, or another case of a stored one | `ILIKE` with `first()`: `john_doe@…` could sign in `john.doe@…` | equality ignoring case. The exact spelling wins; else the only active account equal ignoring case; else the only other one; else nobody. When two accounts differ only by case and neither matches exactly (`ANN@` for `Ann@` and `ann@`), nobody signs in, where before the older account did |
| U-2 | a user signing in | login, registration, password reset | JWT `identity` is the string typed | the stored `user.username` |
| U-3 | an inviter | inviting an address equal ignoring case to an active account | a second, pending account | 400, nothing created. Re-inviting a pending account in another case reuses it |
| U-4 | anyone signing in | an active and a pending account equal ignoring case | `first()` by id, often the pending shell | the active account |
| U-5 | any signed-in user on `/user/change-username`; a user editor on `PATCH /api2/user/<id>` | a new username equal ignoring case to another account's | the page refused it ("already in use", through flask-user's `ILIKE`, which also refused pattern matches such as `j_hn.doe`); `PATCH` accepted it | both refuse it: the page shows the form again with "already in use"; `PATCH` answers 400 `Another account has this username.` and writes nothing. The page now accepts pattern-matching look-alikes, which sign in only the renamed account (unit 9) |
| T-1 | the holder of a session issued by WP-0k | after its account is deleted, or renamed, and another account takes the username | signed in the other account, for up to 365 days | anonymous |
| T-2 | the holder of an API token | after its account is deleted and the username recreated, with the token's validity cached | 200 as the new account for up to 10 minutes (WP-2b T1) | 401. The row is read on every request: one primary-key lookup |
| T-3 | the holder of a token with no account id: a session issued before WP-0k (up to 365 days) or a render token (120 s) | after the account its username names was created later than the token | signed in the new account (WP-2b T2) | anonymous. See the rule below the table |

T-3 in detail:
- **Whole seconds.** `iat` has whole seconds, so the token is refused only when `created` is in a later second. A token issued in the same second as the account is accepted.
- **One clock.** The database compares, `created >= CAST(to_timestamp(iat + 1) AS TIMESTAMP)` on Postgres, so both values are on the clock that wrote `created` (`current_timestamp()` in the session time zone). Tested at UTC, +02:00 and -05:00.
- **No `created`.** An account with no `created` keeps accepting such tokens. Only accounts created before migration 853e0e8aa6a0 (2019-09) lack one: every insert since goes through the model default, and a recreated account always has one, so the attack T-3 closes is not reopened.
- **Residual.** An account created before the token and renamed to its username after it still inherits it (Human acceptance).

## Human acceptance

Security asks the human to accept:
- Rows L-1 to L-5, U-1 to U-5 and T-1 to T-3.
- **The rename residual of T-3.** `user` records no rename time, so a session issued before WP-0k follows its username to an older account renamed to that username. The residual ends when the last pre-WP-0k session expires, 365 days after deploy. The alternative is to rotate `JWT_SECRET_KEY` when deploying WP-0k: every pre-WP-0k session and render token ends at once, every user signs in again, and API tokens, signed with the same key, must be reissued. Recommended: accept the residual. Renames are rare, and WP-0j refuses renames of accounts holding more than the caller.
- **T-3 for accounts with no `created`** (created before 2019-09): pre-WP-0k sessions keep signing them in.
- **Case-only duplicates.** Accounts equal ignoring case now sign in only by their exact spelling. Before deploying, list them with `SELECT lower(username), count(*) FROM "user" GROUP BY 1 HAVING count(*) > 1`, and merge or rename them.
- **One database clock.** T-3 assumes the Postgres session time zone is the same when `created` is written and when a token is checked. That holds while no client sets its own `TimeZone`; Harmony's connections do not.

## Carried risks

- **WP-5a and later.** The FastAPI `PrincipalDep` must port the three C-5 rules, and its login must mint `user_id`.
- **WP-1h.** Render tokens still name the account by username and rely on T-3. The renderer's resource-scoped token (SEC-7) replaces them.
- **WP-5d.**
  - Reset links are still multi-use (SEC-6; WP-0j security C5).
  - Usernames compare ignoring case but are unique only as stored. A unique index on `lower(username)` belongs with the user-model port, after the duplicates are merged.
- **Unit 1 severity.** Where gunicorn is reachable without nginx-proxy, or behind a proxy forwarding `$http_host`, reset-link poisoning was High before this WP. Behind the stock nginx-proxy it was Low. Closed in the app either way.

## Requests

- [ ] qa: in this WP's stack, merged with WP-0j as one step, flip WP-2b's pins in `tests/authz/http/test_api_tokens.py` and add two:
  - (a) T1 `test_used_api_token_of_a_deleted_user_signs_in_as_the_recreated_username`: 200 as the new account today, 401 after, with no timing bound any more;
  - (b) T2 `test_login_token_of_a_deleted_user_signs_in_as_the_recreated_username`: 200 as the new account today, 401 after;
  - (c) new, T-3: a token minted the pre-WP-0k way (`identity` and the old `user_claims`, no `user_id`) before a delete and recreate signs in the new account today, and nobody after;
  - (d) new, U-1: a look-alike account (`<x>_doe` beside `<x>.doe`) signing in through `POST /api2/authentication/login` gets the older account today, and its own after.
  - The never-used-token control stays 401.
- [ ] lead: land WP-0i, then WP-0j and WP-0k together (section "Merging with WP-0j"). The merge applies `WP-0k-evidence/merge-with-0j/privilege_escalation.patch`.

## Log

- 2026-10-05 backend-0k unit 1: nginx-proxy 1.11.6 does not forward the raw Host: `@` in Host is 400, unserved hosts 503, the upstream Host is the normalised `$host`; direct to gunicorn a forged Host or `SCRIPT_NAME` poisons the reset link. Check: `WP-0k-evidence/unit1-nginx-host/probe-before.md` (22 raw requests on the WP-2c stack plus nginx-proxy, links read from mailpit).
- 2026-10-05 backend-0k unit 2: reset, invite, access-granted and new-dashboard links built by `web/server/util/deployment_links.py` (WP-0i's `deployment_origin` moved there) from `DEPLOYMENT_BASE_URL` and the URL map; the access-granted email links the dashboard's slug, not its resource name (9076899). Multi-item `with` statements nested so the web image's Python 3.8 parses the formatted files (1740a02). Check: `uv run pytest tests/web/links` 35 failed on 35e9a2d, each for a request-derived host, scheme, port, script root or the `_` slug; 35 passed after; `uv run pytest tests/web` 272 passed, 1 xfailed; `uv run --locked mypy` clean; ruff check and format clean on the touched files; every `web/server` file parses on the image's Python 3.8.20; live, the same 22 requests as unit 1 mail every reset link on the configured origin (`probe-after-unit2.md`).
- 2026-10-05 backend-0k unit 3: `share_via_email` and `/api2/share/email` link the dashboard or Advanced Query page on the configured origin and take only the locale and a well-formed `#h=` hash from the caller's link (3f41aa0). Check: `uv run pytest tests/web/links/test_share_links.py` 11 failed and 6 passed on 0487b28's code (the 6 are links already on the origin, or none), 17 passed after; `uv run pytest tests/web` 289 passed, 1 xfailed; live, a forged Host and hostile `queryUrl` values mail only `https://harmony_demo.zenysis.com/[fr/]advanced-query[#h=…]` (`unit3-share-links/probe-after.md`).
- 2026-10-05 backend-0k unit 4: every username lookup goes through `web/server/security/usernames.py` (exact, else the one account equal ignoring case, else nobody); flask-user uses it through `UsernameAdapter`; login and registration mint the JWT for `user.username`; invitations compare `lower(username)` (1447d35). Check: `uv run pytest tests/web/usernames` 33 failed and 22 passed with `web/server` at 3f41aa0, 55 passed after; `uv run pytest tests/web` 344 passed, 1 xfailed; mypy clean; live on Postgres, the look-alike's registration signs in as `jane.doe` before and as `jane_doe` after, and re-inviting a mixed-case account makes a second account before and 400 after (`unit4-usernames/probe-before.md`, `probe-after.md`); pre-WP-0k cookies keep signing in their account (`legacy-cookies-after.md`); WP-2b pure layer identical on base and head (4663 passed, 580 skipped, the same 12 WP-0i render-pin errors).
- 2026-10-05 backend-0k unit 5: three-model interrogate of units 2 to 4; share-link locale must be one Harmony has, the session hash is the last well-formed `#h=`, an unparseable link falls back to the plain page, `?source=` goes before the fragment, the access-granted email skips and logs a dashboard with no slug (f701e1c). Check (re-run by backend-0k after the restart): the new link tests from f701e1c on fcbef95's code 21 failed, 37 passed. f701e1c and 129125d were committed in the same second by the lost builder: at f701e1c alone `tests/web` has 11 failures, all reset-link tests patching `admin.find_user_by_username`, which 129125d adds; at 129125d `uv run --locked pytest tests/web` 387 passed, 1 xfailed.
- 2026-10-05 backend-0k unit 6: sessions carry `user_id`, API tokens are checked against their row's `user_id`, sign-in prefers an active account, flask-user's change-username page and `PATCH /api2/user/<id>` refuse a username equal ignoring case to another account's, `forgot_password` resolves the account like sign-in (129125d). Check (re-run after the restart): `tests/web/usernames` from 129125d on f701e1c's code 20 failed, 72 passed (token binding, case-equal renames on both paths, active-over-pending, stored-username identity); 92 passed at 129125d.
- 2026-10-05 backend-0k unit 7: a token with no account id (a session minted before WP-0k, a render token) is refused when its `iat` is earlier, to the second, than the account's `created`; an account with no `created` keeps accepting it (`issued_before_account` in `signal_handlers.py`). Check: `tests/web/usernames` on 129125d's code 2 failed (`does_not_sign_in_a_recreated_account`: 12 signed in; `is_refused_by_an_account_created_after_it`: 1 signed in), 93 passed; 95 passed after; `uv run --locked pytest tests/web` 390 passed, 1 xfailed; `uv run --locked mypy` no issues in 519 files.
- 2026-10-05 backend-0k unit 8: the login loader reads the API token's row on every request instead of memoising it for `CACHE_DEFAULT_TIMEOUT` (10 minutes), so no cached owner outlives a revoke or a user delete; `update_user_api_tokens` no longer clears a memo. One primary-key lookup per API-token request. Check: `test_api_token_is_refused_once_its_account_is_deleted_even_if_the_id_returns` (token used, account deleted, recreated under the same id) failed on unit 7's code with the cache fake (`assert 2 is None`), passes after; `uv run --locked pytest tests/web` 391 passed, 1 xfailed; mypy clean.
- 2026-10-05 backend-0k unit 7, round 2 (lead): 370f756 compared `iat` (UTC) with `created` in Python, but Postgres writes `created` with `current_timestamp()` in the session zone, so the rule failed open behind UTC and refused valid tokens ahead of it. The database now compares: `created >= database_time_from_epoch(iat + 1)` (`CAST(to_timestamp(iat) AS TIMESTAMP)` on Postgres, `datetime(iat, 'unixepoch')` on SQLite, whose `current_timestamp` is UTC); a NULL `created` matches nothing, so the token stays accepted (INV-3 row T-3). Check: `tests/web/usernames/test_token_clock_postgres.py` (marked `stack`: it starts the pinned `postgres@sha256:f7d2…` with `docker run`, one database per zone, accounts created through the model so `created` takes the column default) on 370f756's code 3 failed, 9 passed: `Etc/GMT-2` refused a session issued 2 s after the account and one issued in its creation second, `Etc/GMT+5` signed in a session issued 2 s before the account; 12 passed after; `uv run --locked pytest tests/web` 403 passed, 1 xfailed (391 with `-m 'not stack'`, as CI runs); mypy clean; the container is removed after the module.
- 2026-10-05 backend-0k unit 9: WP-0j security C1 covered on both rename paths. `test_a_look_alike_rename_by_patch_signs_in_only_the_renamed_account` runs `UserResource.update_user` (the `PATCH /api2/user/<id>` handler, with its WP-0k `username_taken` check) to rename account 6 to `j_hn.doe@…`, which pattern-matches `john.doe@…`; the existing change-username-page test does the same through flask-user's `/user/change-username`. Both then sign in the look-alike by login and by a pre-WP-0k session, and get account 6, while `john.doe` still gets account 1. Check: with `web/server` at 3f41aa0 (before unit 4) both fail: PATCH `assert 1 == 6` (the look-alike's login signs in `john.doe`), the page `assert 200 == 302` (flask-user's ILIKE lookup called the look-alike taken); both pass on the head; `uv run --locked pytest tests/web -m 'not stack'` 392 passed, 1 xfailed. No rename is refused for merely pattern-matching another username: once lookups are exact, `j_hn.doe` is an ordinary distinct username (C2 refuses only equality ignoring case).
- 2026-10-05 backend-0k unit 10: merged WP-0i's head 3b14989 (c2736ad; conflicts: the backend memory index, kept both lines, and `tests/web/render/test_render_origin.py`, took WP-0i's `render_fakes` import and kept WP-0k's `deployment_links` import) and `mig/integration` 3e538e2; the evidence probes now pass the lint gate (c91bb38); the username fixture creates the empty grant tables a user edit reads, so the PATCH rename test runs on the WP-0j merge too (84f0049 and this commit). Check on this branch: `ci/lint_python.sh mig/integration` clean (50 files formatted); `uv run --no-project -p cpython-3.8.20 python ci/check_py38_syntax.py config data db log models graphql util web scripts tests/web` 865 files, 0 problems; `uv run --locked mypy` no issues in 519 files; `ci/pytest_suites.sh` all 8 suites passed (core 25, druid 1, druid_setup 79, golden 269, graphql 22, pipeline 129 + 1 skipped, toolchain 12, web 393 + 12 `stack` deselected, 1 xfailed); `uv run --locked pytest tests/web` 405 passed, 1 xfailed. Scratch merge of `mig/WP-0j-rename-reset-guard` 19b9f62 into c91bb38 (detached worktree, not pushed): four conflicts, all imports or one line (below, "Merging with WP-0j"); `tests/privilege_escalation` 122 passed after the three harness edits in `WP-0k-evidence/merge-with-0j/privilege_escalation.patch` (47 failed or errored without them: 35 on the mailer stub patching `admin.url_for`, 12 on `create_user_access_token(username)`); `tests/web` 405 passed, 1 xfailed; mypy no issues in 520 files; 3.8 guard over the same paths plus `tests/privilege_escalation` 869 files, 0 problems; ruff clean.

## Evidence

- **Unit 1, nginx-proxy and the Host header:** `WP-0k-evidence/unit1-nginx-host/README.md`, with the overlay, the probes and their output.
- **Units 2 and 3, live links:** `unit1-nginx-host/probe-after-unit2.md`, `unit3-share-links/probe-after.md`.
- **Unit 4, live usernames on Postgres:** `unit4-usernames/probe-before.md`, `probe-after.md`, `legacy-cookies-after.md`.
- **Units 5 to 9, tests:** `tests/web/links`, `tests/web/usernames` (SQLite, plus `test_token_clock_postgres.py` on a throwaway Postgres at three time zones). Each unit's log line gives the counts on the code before it and after it.
- **Unit 10, merges and gates:** the log line; `merge-with-0j/` holds the harness patch and the resolved conflicts for the WP-0j merge.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
