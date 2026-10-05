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
7. **Tokens with no account id sign in only an account created no later than they were issued** (lead addition a, the INV-3 decision for already-issued tokens). A session minted before WP-0k, or a render token, is refused when its `iat` is earlier, to the second, than the account's `created`. Check: the recreate case fails on 129125d and passes after; same-second, no-`created` and rename-residual cases pinned.
8. **The API token check reads the row on every request** (lead addition a: the validity cache must not outlive a user delete). Check: a token used before its user is deleted and recreated under the same id (SQLite id reuse) signs in on 7's head and is refused after.
9. **Look-alike renames on both paths reach only the renamed account** (WP-0j security C1). Check: `PATCH /api2/user/<id>` and `/user/change-username` renames to `j_hn.doe` (pattern-matches `john.doe`) sign in only the renamed account, failing with `web/server` at 3f41aa0 and passing after.
10. **Merge WP-0i's head and `mig/integration`; trial merge with WP-0j and its harness.** Check: `tests/web`, `ci/lint_python.sh`, `ci/check_py38_syntax.py`, `uv run --locked mypy`, and `tests/privilege_escalation` on a scratch merge with `mig/WP-0j-rename-reset-guard`.
11. **INV-3 table, human acceptance list, requests (qa flips WP-2b T1 and T2), carried risks, merge-together rule.** Then `status: review`.

## Contract changes

None planned. C-5 (the `accessKey` JWT) keeps its layout; only the value of `identity` becomes the stored `user.username` instead of the string the user typed.

## Requests

## Log

- 2026-10-05 backend-0k unit 1: nginx-proxy 1.11.6 does not forward the raw Host: `@` in Host is 400, unserved hosts 503, the upstream Host is the normalised `$host`; direct to gunicorn a forged Host or `SCRIPT_NAME` poisons the reset link. Check: `WP-0k-evidence/unit1-nginx-host/probe-before.md` (22 raw requests on the WP-2c stack plus nginx-proxy, links read from mailpit).
- 2026-10-05 backend-0k unit 2: reset, invite, access-granted and new-dashboard links built by `web/server/util/deployment_links.py` (WP-0i's `deployment_origin` moved there) from `DEPLOYMENT_BASE_URL` and the URL map; the access-granted email links the dashboard's slug, not its resource name (9076899). Multi-item `with` statements nested so the web image's Python 3.8 parses the formatted files (1740a02). Check: `uv run pytest tests/web/links` 35 failed on 35e9a2d, each for a request-derived host, scheme, port, script root or the `_` slug; 35 passed after; `uv run pytest tests/web` 272 passed, 1 xfailed; `uv run --locked mypy` clean; ruff check and format clean on the touched files; every `web/server` file parses on the image's Python 3.8.20; live, the same 22 requests as unit 1 mail every reset link on the configured origin (`probe-after-unit2.md`).
- 2026-10-05 backend-0k unit 3: `share_via_email` and `/api2/share/email` link the dashboard or Advanced Query page on the configured origin and take only the locale and a well-formed `#h=` hash from the caller's link (3f41aa0). Check: `uv run pytest tests/web/links/test_share_links.py` 11 failed and 6 passed on 0487b28's code (the 6 are links already on the origin, or none), 17 passed after; `uv run pytest tests/web` 289 passed, 1 xfailed; live, a forged Host and hostile `queryUrl` values mail only `https://harmony_demo.zenysis.com/[fr/]advanced-query[#h=…]` (`unit3-share-links/probe-after.md`).
- 2026-10-05 backend-0k unit 4: every username lookup goes through `web/server/security/usernames.py` (exact, else the one account equal ignoring case, else nobody); flask-user uses it through `UsernameAdapter`; login and registration mint the JWT for `user.username`; invitations compare `lower(username)` (1447d35). Check: `uv run pytest tests/web/usernames` 33 failed and 22 passed with `web/server` at 3f41aa0, 55 passed after; `uv run pytest tests/web` 344 passed, 1 xfailed; mypy clean; live on Postgres, the look-alike's registration signs in as `jane.doe` before and as `jane_doe` after, and re-inviting a mixed-case account makes a second account before and 400 after (`unit4-usernames/probe-before.md`, `probe-after.md`); pre-WP-0k cookies keep signing in their account (`legacy-cookies-after.md`); WP-2b pure layer identical on base and head (4663 passed, 580 skipped, the same 12 WP-0i render-pin errors).
- 2026-10-05 backend-0k unit 5: three-model interrogate of units 2 to 4; share-link locale must be one Harmony has, the session hash is the last well-formed `#h=`, an unparseable link falls back to the plain page, `?source=` goes before the fragment, the access-granted email skips and logs a dashboard with no slug (f701e1c). Check (re-run by backend-0k after the restart): the new link tests from f701e1c on fcbef95's code 21 failed, 37 passed. f701e1c and 129125d were committed in the same second by the lost builder: at f701e1c alone `tests/web` has 11 failures, all reset-link tests patching `admin.find_user_by_username`, which 129125d adds; at 129125d `uv run --locked pytest tests/web` 387 passed, 1 xfailed.
- 2026-10-05 backend-0k unit 6: sessions carry `user_id`, API tokens are checked against their row's `user_id`, sign-in prefers an active account, flask-user's change-username page and `PATCH /api2/user/<id>` refuse a username equal ignoring case to another account's, `forgot_password` resolves the account like sign-in (129125d). Check (re-run after the restart): `tests/web/usernames` from 129125d on f701e1c's code 20 failed, 72 passed (token binding, case-equal renames on both paths, active-over-pending, stored-username identity); 92 passed at 129125d.
- 2026-10-05 backend-0k unit 7: a token with no account id (a session minted before WP-0k, a render token) is refused when its `iat` is earlier, to the second, than the account's `created`; an account with no `created` keeps accepting it (`issued_before_account` in `signal_handlers.py`). Check: `tests/web/usernames` on 129125d's code 2 failed (`does_not_sign_in_a_recreated_account`: 12 signed in; `is_refused_by_an_account_created_after_it`: 1 signed in), 93 passed; 95 passed after; `uv run --locked pytest tests/web` 390 passed, 1 xfailed; `uv run --locked mypy` no issues in 519 files.

## Evidence

- **Unit 1, nginx-proxy and the Host header:** `WP-0k-evidence/unit1-nginx-host/README.md`, with the overlay, the probes and their output.
## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
