---
wp: "0k"
title: "Build outgoing links from the configured origin; match usernames exactly"
status: review
owner_role: "backend"
instances:
  - name: "lead-1"
    files:
      - scripts/create_user.py
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
      - tests/web/render/render_fakes.py
      - tests/web/test_field_info_route.py
      - tests/web/test_dashboard_unauthorized_redirect.py
      - tests/web/server/test_hasura_proxy.py
      - web/server/routes/views/authentication.py
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
11. **INV-3 table, human acceptance list, requests (qa flips WP-2b T1 and T2), carried risks, merge-together rule** (e3a7064).
12. **Lead round 2, from the interrogate panel.** One rule for every token: load the account by id (the `api_token` row, the `user_id` claim, or for a pre-WP-0k session the one non-pending account its username can mean), and require the exact username and a `created` not after `iat`; render tokens carry `user_id`. Only real renames are checked against other accounts. The admin reset route mails the account it authorised, by id. Registration refuses a pending twin of a registered account. `POST /api2/user` refuses a username equal to another ignoring case. `scripts/create_user.py` is the lead's: requested. Check: each new test fails on e3a7064 and passes after.
13. **Deactivated accounts sign in nowhere** (decision 0010). Password login, header login, the flask-login session, session, API and render tokens refuse an account whose status is not active; `authentication_required` agrees with the loaders. No validity cache is left to invalidate (unit 8). Check: the tests fail on e3a7064 and pass after.
14. **Trial merge with WP-0j's head, gates, documents.** Then `status: review`.

## Contract changes

**C-5, additive.** I own C-5.
- Old: a session JWT's `user_claims` are `needs`, `query_needs` and `remember_me`, and `identity` is the username as typed. API tokens add `id` (their `api_token` row). Render tokens carry narrowed `needs`.
- New: session and render tokens' `user_claims` also carry `user_id`, the account id, and `identity` is the stored `user.username`. API tokens keep their layout.
- Rules every reader of C-5 must enforce (`account_for_token` in `web/server/security/signal_handlers.py`):
  1. The account id comes from the `api_token` row named by `user_claims.id` (read on every request; revoked or missing means nobody), else from `user_claims.user_id`, else, for a session issued before WP-0k, from the one account equal to `identity` ignoring case that is not a pending invitation (none, or two, means nobody).
  2. That account must be active, must have exactly the username in `identity`, and must not have a `created` in a later second than the token's `iat`. The database compares the times in the time zone that wrote `created`. A token with no `iat` signs in nobody.
- Consumers: the Flask login loader (this WP). No other reader exists today. The FastAPI `PrincipalDep` (WP-5a and later) must port both rules. Cookies issued before WP-0k stay valid under rule 1's last branch, so nothing is reissued.

## Merging with WP-0j

**WP-0j and WP-0k merge together, in one step, on one stack.**
- WP-0j guards renames of higher-privileged accounts, but still lets a caller rename itself or a lesser account to a username that pattern-matches an administrator's (WP-0j security C1). Only WP-0k's exact matching makes that harmless.
- WP-0k without WP-0j leaves the H5 rename-then-reset takeover open.
- WP-0k contains WP-0i's head (3b14989), so WP-0i lands first or with them.

The trial merge of `mig/WP-0j-rename-reset-guard` into this branch (unit 10 at 19b9f62; repeated in unit 14 with WP-0j b090396 into 73bd66d) has four conflicts:
- `web/server/api/user_api_models.py` and `permission_api_models.py`: imports only; keep both sides. In `update_user`, keep WP-0k's rename check (`username_taken`, only when the username changes) first, before WP-0j's `can_update_item` and `verify_may_rename`. Its 400 reveals only that a username exists, which `GET /api2/user` shows any signed-in user, and neither refusal writes anything. The reset route merges without a conflict: WP-0j's `verify_may_reset_password(user)` runs first, then WP-0k's `send_reset_password_for_account(user.id)`.
- `web/server/routes/views/users.py`: take WP-0j's `APIToken.is_revoked.is_(False)` line. WP-0k's removal of the token memo merges cleanly.
- The backend memory index: keep both lines.

`tests/privilege_escalation` then needs the three edits in `WP-0k-evidence/merge-with-0j/privilege_escalation.patch`:
- the mailer stub patches `admin.deployment_url` instead of `admin.url_for`, as WP-0j predicted;
- the harness passes the `User` to `create_user_access_token`, which now takes the account, not a username (two helpers and the `make_user` fixture).

With them, at unit 14, the harness gives 132 passed and `tests/web` 426 passed, 3 xfailed. `conflicted-files-vs-0j.diff` is the resolved diff of the three conflicted Python files against WP-0j b090396.

## INV-3 difference table

Rows L are links (units 2, 3, 5), U usernames (units 4, 6, 9, 12), T tokens (units 6 to 8, 12), D deactivated accounts (unit 13). Every other request answers as before.

| # | Principal | Request | Before | After |
|---|---|---|---|---|
| L-1 | anyone, anonymous | `POST /api2/authentication/forgot_password`, and the admin `POST /api2/user/<id>/reset_password`, with a forged `Host` or `SCRIPT_NAME`, or behind TLS termination | the mailed reset link takes the request's scheme, host and script root | the link is on `DEPLOYMENT_BASE_URL`, https. Behind the stock nginx-proxy only a served host ever reached the app (unit 1), so there the visible change is `https://` instead of `http://` |
| L-2 | a caller allowed to invite | `POST /api2/user/invite` | invite link on the request host | on the configured origin |
| L-3 | a caller granting dashboard roles | access-granted email | link on the request host, to `/dashboard/<resource name>` | on the configured origin, to `/dashboard/<slug>?source=…`. A dashboard with no slug mails nothing and logs a warning; the role change is still committed |
| L-4 | a dashboard creator | new-dashboard email | request host | configured origin, `?source=` before any fragment |
| L-5 | a signed-in user sharing by email | `POST /api2/dashboard/<id>/share_via_email` (`dashboardUrl`), `POST /api2/share/email` (`queryUrl`) | the caller's free-form URL is mailed as the link | the dashboard's page, or the Advanced Query page, on the configured origin, taking from the caller's link only a locale Harmony has and the last well-formed `#h=` hash. An unparseable link gives the plain page |
| U-1 | anyone typing a username: password login, registration, `X-Username` and `X-Password`, flask-user pages, role assignment by username, invitations, `forgot_password` | a username containing `_` or `%`, or another case of a stored one | `ILIKE` with `first()`: `john_doe@…` could sign in `john.doe@…` | equality ignoring case. The exact spelling wins; else the only active account equal ignoring case; else the only other one; else nobody. When two accounts differ only by case and neither matches exactly (`ANN@` for `Ann@` and `ann@`), nobody matches, where before the older account did. A password still has to match |
| U-2 | a user signing in | login, registration, password reset | JWT `identity` is the string typed | the stored `user.username`, plus `user_id` |
| U-3 | an inviter | inviting an address equal ignoring case to an active account | a second, pending account | 400, nothing created. Re-inviting a pending account in another case reuses it |
| U-4 | anyone typing a username | an active and a pending account equal ignoring case | `first()` by id, often the pending shell | the active account |
| U-5 | any signed-in user on `/user/change-username`; a user editor on `PATCH /api2/user/<id>` | a new username equal ignoring case to another account's | the page refused it ("already in use", through flask-user's `ILIKE`, which also refused pattern matches such as `j_hn.doe`); `PATCH` accepted it | both refuse it: the page shows the form again with "already in use"; `PATCH` answers 400 `Another account has this username.` and writes nothing. Only a changed username is checked, so an account of a case-only pair can still be edited, and can submit its own name on the page. The page now accepts pattern-matching look-alikes, which sign in only the renamed account (unit 9) |
| U-6 | a caller with `reset_password` on a user | `POST /api2/user/<id>/reset_password` on an account with a case-only twin | the reset was looked up again by username, so the link for a pending `dup.shell@` was stored on and mailed to the active `Dup.Shell@` | the account the route authorised gets it |
| U-7 | an invitee | `POST /api2/authentication/register` for a pending account equal ignoring case to a registered (active or deactivated) one | 200; a second active account, and sessions named by that username could move to it | 400 `Another account has this email address`; nothing written |
| U-8 | a caller passing Potion's create check on users | `POST /api2/user` with a username equal ignoring case to another account's | 200 or 201; a case-only twin | 400 `Another account has this username.`; nothing written |
| T-1 | the holder of a session issued by WP-0k | after its account is deleted, or renamed, and another account takes the username | signed in the other account, for up to 365 days | anonymous |
| T-2 | the holder of an API token | after its account is deleted and the username recreated, with the token's validity cached | 200 as the new account for up to 10 minutes (WP-2b T1) | 401. The row is read on every request: one primary-key lookup |
| T-3 | the holder of any token | after an account is created, in a later second than the token was issued, with the id or the username the token names | signed in the new account (WP-2b T2 for sessions without `user_id`) | anonymous. See the rule below the table |
| T-4 | the holder of a session or API token | after the account's username changes in any way, case included | a session or API token kept working across a case-only change (an `ILIKE` lookup), not across a real rename | anonymous after any change: the token names the exact username. A user who renames themselves on the change-username page signs in again; an integration whose account is renamed needs a new API token |
| T-5 | the holder of a session issued before WP-0k for an account of a case-only pair (both registered) | any request | `ILIKE` with `first()` picked one account of the pair, not necessarily the one that signed in | anonymous: that username can mean either account. The owners sign in again and get a session bound by id |
| T-6 | the holder of a session issued before WP-0k whose username matches only pending invitations | any request | the pending account | anonymous; a pending account never signed in |
| D-1 | the owner of a deactivated account | `POST /api2/authentication/login` with the right password | 200 and a new 365-day token | 400 `invalid_login_credentials`, the same body as a wrong password |
| D-2 | the owner of a deactivated account | any request with `X-Username` and `X-Password` | 200 as the account | anonymous: 401 on API routes, the sign-in page on pages |
| D-3 | the holder of any token (session, pre-WP-0k session, API token, render token) issued before the account was deactivated | any request | 200 as the account | anonymous, from the next request: there is no validity cache (unit 8) |
| D-4 | a browser with a flask-login session cookie of a deactivated account | any request | signed in | anonymous |

T-3 in detail:
- **Whole seconds.** `iat` has whole seconds, so a token is refused only when `created` is in a later second. A token issued in the same second as the account is accepted.
- **One time zone, not one clock.** Postgres writes `created` with `current_timestamp()` in the session time zone, as a naive timestamp. The database compares, `created < CAST(to_timestamp(iat + 1) AS TIMESTAMP)`, so both sides are in the time zone current at the check. Tested at UTC, +02:00 and -05:00. If the server's `TimeZone` setting changes, rows written before the change are misread by the difference: a move to a zone further east accepts a token up to the offset before an account's creation, a move west refuses valid tokens for that long. Making `created` a `timestamptz` removes this (request to core).
- **No `created`.** An account with no `created` is not checked against `iat`. Accounts created before migration 853e0e8aa6a0 (2019-09) have none, and so do rows written outside the ORM: the column has an ORM default, not a server default. Every path in `web/` and `scripts/` writes users through the ORM. A server default needs a migration (request to core); without one, a row written by hand or by SQL can be signed into by an older token naming its id or username.
- **Residual.** A session issued before WP-0k follows its username to an account created before the session and renamed to that username after it (Human acceptance).

## Human acceptance

Security asks the human to accept:
- Rows L-1 to L-5, U-1 to U-8, T-1 to T-6 and D-1 to D-4.
- **Deactivated accounts lose access at once (decision 0010).** Any integration that relies on a deactivated account's API token, or on its `X-Username`/`X-Password`, stops working at deploy. Before deploying, list them with `SELECT username FROM "user" WHERE status_id <> 1 AND id IN (SELECT user_id FROM api_token WHERE NOT is_revoked)` and reactivate or reissue as needed.
- **A rename ends the account's sessions and API tokens (T-4)**, a change of case included.
- **The rename residual of T-3.** `user` records no rename time, so a session issued before WP-0k follows its username to an older account renamed to that username. It ends when the last pre-WP-0k session expires, 365 days after deploy. The alternative is to rotate `JWT_SECRET_KEY` when deploying WP-0k: every pre-WP-0k session and render token ends at once, every user signs in again, and every API token, signed with the same key, must be reissued. Recommended: accept the residual. Renames are rare, and WP-0j refuses renames of accounts holding more than the caller.
- **Accounts with no `created`** (created before 2019-09, or written outside the ORM) are not checked against `iat` (T-3).
- **The database's `TimeZone` setting must not change** while pre-WP-0k sessions live, or until `created` becomes a `timestamptz` (T-3).
- **Case-only duplicates.** Accounts equal ignoring case sign in by typed username only with their exact spelling (U-1), and their pre-WP-0k sessions end (T-5). Before deploying, list them with `SELECT lower(username), count(*) FROM "user" GROUP BY 1 HAVING count(*) > 1`, and merge or rename them.

## Carried risks

- **WP-5a and later.** The FastAPI `PrincipalDep` must port both C-5 rules, the active-status check and the login refusal, and its login must mint `user_id`.
- **WP-5d.**
  - Reset links are still multi-use (SEC-6; WP-0j security C5).
  - Usernames compare ignoring case but are unique only as stored. Every write path now checks `username_taken` first, but two concurrent writes can still race. A unique index on `lower(username)` closes that; it belongs with the user-model port, after the legacy case-only pairs are merged.
- **CI does not run the Postgres clock test.** `tests/web/usernames/test_token_clock_postgres.py` is marked `stack` and CI's unit job deselects `stack`, so only the SQLite form of `database_time_from_epoch` runs in CI (request to infra).
- **Unit 1 severity.** Where gunicorn is reachable without nginx-proxy, or behind a proxy forwarding `$http_host`, reset-link poisoning was High before this WP. Behind the stock nginx-proxy it was Low. Closed in the app either way.

## Requests

- [ ] qa: in this WP's stack, merged with WP-0j as one step, flip WP-2b's pins in `tests/authz/http/test_api_tokens.py` and add three:
  - (a) T1 `test_used_api_token_of_a_deleted_user_signs_in_as_the_recreated_username`: 200 as the new account today, 401 after, with no timing bound any more;
  - (b) T2 `test_login_token_of_a_deleted_user_signs_in_as_the_recreated_username`: 200 as the new account today, 401 after;
  - (c) new, T-3: a token minted the pre-WP-0k way (`identity` and the old `user_claims`, no `user_id`) before a delete and recreate signs in the new account today, and nobody after;
  - (d) new, U-1: a look-alike account (`<x>_doe` beside `<x>.doe`) signing in through `POST /api2/authentication/login` gets the older account today, and its own after;
  - (e) new, D-1 to D-3: a deactivated account's password login (200 today, 400 `invalid_login_credentials` after), header login and earlier API token (200 today, 401 after).
  - The never-used-token control stays 401.
- [x] lead: `scripts/create_user.py` still looks usernames up with `ILIKE` (`-o john_doe@…` overwrites `john.doe@…`). The change and its check are in `WP-0k-evidence/requests/create_user.md`. Done by the lead on 2026-10-05: the script finds the account with `find_user_by_username` and refuses a username another account equals ignoring case; the two strict xfails became passes (test_account_targets.py 9 passed); ruff and the 3.8 compile clean.
- [ ] core (optional, not blocking): a migration giving `user.created` a server default, and making it `timestamptz` (`USING created AT TIME ZONE current_setting('TimeZone')`), so rows written outside the ORM are checked and a `TimeZone` change cannot shift T-3. `signal_handlers.database_time_from_epoch` then becomes `to_timestamp(iat)`.
- [ ] infra (optional): run `tests/web/usernames -m stack` in a CI job with docker, or split a `postgres` marker from `stack`.
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
- 2026-10-05 backend-0k unit 11: INV-3 table, C-5 change, merge rule with WP-0j, acceptance, risks, requests (e3a7064).
- 2026-10-05 backend-0k units 12 and 13 (lead round 2 from the interrogate panel; decision 0010): `account_for_token` replaces the per-kind binding (every token: account by id, exact username, active, `created` not after `iat`; a pre-WP-0k session gets the one non-pending account its username can mean, B's finding 1, which the lead's ruling had left with the typed-input arbitration: that arbitration's exact-spelling preference handed `ann@` tokens to the other account of a pair); render tokens carry `user_id`; `update_user` and `username_is_available` check only real renames; `send_reset_password_for_account(user.id)` for the admin route; registration refuses a pending twin of a registered account (`username_taken(..., ignore_pending=True)`); `before_create_user` on `UserResource`; `try_authenticate_user`, `HarmonyUserManager.get_user_by_id` and `authentication_required` refuse deactivated accounts; `database_time_from_epoch` gets a default compiler that raises, and its docstring says "time zone", not "clock" (73bd66d). Check: the new and changed tests in `tests/web/usernames` and `tests/web/render/test_render_route_guards.py` on e3a7064's code 31 failed, 230 passed (`/tmp/wp0k-round2-before.txt`: admin reset mails 10 not 11, the pending twin registers, `POST /api2/user` takes case twins, every deactivated-account path signs in, case-only-pair PATCH and own-name page refused, a same-id same-username recreate and a case-only rename keep the token, `ann@`/`Ann@` legacy tokens pick an account, render tokens lack `user_id`); after, `uv run --locked pytest tests/web` 426 passed, 3 xfailed (the 2 strict xfails are the `create_user.py` request); four other suites' fake users gained `is_active` (`test_field_info_route.py`, `test_dashboard_unauthorized_redirect.py`, `server/test_hasura_proxy.py`) and `test_timeout_route.py` patches `account_for_token`. `scripts/create_user.py` edit refused by the ownership hook (lead's file): requested.
- 2026-10-05 backend-0k unit 14: trial merge of WP-0j b090396 into 73bd66d (scratch worktree, not pushed): the same four conflicts, resolved as in "Merging with WP-0j"; with the harness patch `tests/privilege_escalation` 132 passed, `tests/web` 426 passed, 3 xfailed, mypy no issues in 520 files, 3.8 guard 871 files 0 problems, ruff E9/F63/F7/F82 clean. On this branch: `ci/lint_python.sh mig/integration` clean (51 files formatted), 3.8 guard 867 files 0 problems, `uv run --locked mypy` no issues in 519 files, `ci/pytest_suites.sh` all 8 suites passed (web 414 + 12 `stack` deselected + 3 xfailed), and with docker `tests/web` 426 passed including the Postgres clock test at three zones.

- 2026-10-05 backend-0k unit 14, integration: merged `mig/integration` 298f9d9 (e52c95e; one conflict, the backend memory index, kept every line). `tests/web/test_request_id_logging.py` (from integration) called `login_user` with a username; it now passes an account. Check: `uv run --locked pytest tests/web` 468 passed, 3 xfailed; mypy no issues in 520 files; `ci/lint_python.sh mig/integration` clean (56 files); 3.8 guard 878 files, 0 problems; `ci/pytest_suites.sh`: every suite passes except `tests/authz`, whose 12 errors are WP-2b's render-route pins patching `page_renderer.Transaction`, which WP-0i removed (the same 12 on a scratch merge of WP-0i's head into integration 298f9d9: 4663 passed, 583 skipped, 12 errors; qa flips them with WP-0i).

## Interrogate (units 6 to 9)

`pstack:interrogate` on `git diff f701e1c..84f0049 -- web/server`, three reviewers (opus, fable, sonnet), prompt at `/tmp/wp0k-interrogate-prompt.md`. The lead received A's and C's reports and ruled on them (round 2); B's report reached me. Outcome:

- **Acted on (unit 12):** the rename check blocked every PATCH of a case-only pair account (A, C; lead 1); the admin reset re-resolved by username (lead 2); registration activated a pending twin (lead 3); id-bound tokens still resolved by username, and the `iat` check covered only unbound tokens (B 2, lead 4); Potion's inherited create and `create_user.py` skipped the case check (B 3, lead 5; the script is requested); "same clock" wording and the NULL `created` note (B 4, lead 6); render tokens without `user_id` (B 7, lead); a pre-WP-0k token for a case-only pair went to the exactly spelled account (B 1, adopted: fails closed, T-5); `.order_by` vestigial and no default compiler (B 8).
- **Acted on (unit 13):** deactivated accounts keep tokens (B 6; decision 0010).
- **Recorded, not changed:** a `TimeZone` change shifts T-3 (B 4: residual, core request for `timestamptz`); CI does not run the Postgres compile path (B 5: infra request); no unique index on `lower(username)` (B 3: WP-5d).

## Evidence

- **Unit 1, nginx-proxy and the Host header:** `WP-0k-evidence/unit1-nginx-host/README.md`, with the overlay, the probes and their output.
- **Units 2 and 3, live links:** `unit1-nginx-host/probe-after-unit2.md`, `unit3-share-links/probe-after.md`.
- **Unit 4, live usernames on Postgres:** `unit4-usernames/probe-before.md`, `probe-after.md`, `legacy-cookies-after.md`.
- **Units 5 to 9, 12, 13, tests:** `tests/web/links`, `tests/web/usernames` (SQLite, plus `test_token_clock_postgres.py` on a throwaway Postgres at three time zones). Each unit's log line gives the counts on the code before it and after it.
- **Unit 10, merges and gates:** the log line; `merge-with-0j/` holds the harness patch and the resolved conflicts for the WP-0j merge.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | changes-requested | 2026-10-06 qa-0k at 299c632: 203 tests pass incl. the Postgres clock test (TimeZone UTC, Etc/GMT-2, Etc/GMT+5 verified; a UTC-compare mutant fails three cases); 29 of the claimed 31 fail before on behaviour; live on the trial merge 64 of 66 checks pass vs 43 of 65 failing on base: configured links under forged Host and X-Forwarded, wildcards gone, case twins refused, admin reset of a pending twin correct, tokens end on rename, delete, same-id recreate and revocation, every deactivated path refused with the wrong-password body, pre-WP-0k sessions as recorded, create_user.py exact; lint, 3.8 guard (879), mypy clean. High: integration f5d5993 tests/web/test_api_token_issue.py imports check_token_validity which WP-0k deleted, tests/web fails collection on the merge; merge f5d5993 and port the three asserts to api_token_user_id is not None (users.py takes is_revoked.is_(False); test_redis_password.py keeps bare_flask_app). Medium: (2) authentication_api_models.py:176-179 with setup.py:57-60 get_user_by_id returns None for non-active accounts so POST reset_password gives 500 for pending or deactivated accounts following a mailed link; refuse with a clean 4xx, decide pending resets, INV-3 row, fail-before test; check flask-user's reset and confirm views. (3) WP-0k.md:84-100 Merging with WP-0j is stale (users.py clean; keep issue_api_token and replace_user_acls; privilege_escalation 119 passed 40 failed from WP-2g's logger propagation double-counting WP-0j's caplog, not WP-0k). Low: (4) row U-6 Before column wrong against main; (5) row U-1 says exact spelling wins but usernames.py:40 ranks active first, create_user.py -o consequences; (6) add a test-client POST /api2/user case and fix the 31 count. Info for security: core.py:47-66 matches Resource.name with ILIKE (underscores in dashboard names are wildcards). Pins beyond (a) to (e) listed in the QA report for qa-0k-pins. |
| reviewer | pending | |
| security | pending | |
