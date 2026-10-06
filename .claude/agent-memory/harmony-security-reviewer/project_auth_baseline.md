---
name: harmony-auth-baseline
description: Verified pre-migration facts about Harmony's legacy Flask auth (CSRF, cookies, token claims, redirects) as of WP-0c review 2026-10-04; check before rating session/CSRF findings
metadata:
  type: project
---

These were verified in the WP-0c review on 2026-10-04 against `mig/integration` and `mig/WP-0c-pure-mistake-bugs`. Re-check them after WP-5a or WP-5d lands.

- **No CSRF protection anywhere.** There is no CSRFProtect, and `JWT_CSRF_METHODS = []` (`web/server/configuration/flask.py`). The `accessKey` and session cookies carry no SameSite and no Secure. Any route whose state change becomes effective is therefore reachable by a cross-site form POST in Firefox and Safari. Chrome's Lax default blocks it, except in the 2-minute Lax+POST window.
  **Why:** SEC-5 is owned by WP-5d. Logout-only effects were rated Low in WP-0c, not Medium.
  **How to apply:** rate new CSRF exposure by what the forged request changes. Route the fix to WP-5d unless the WP removes an existing protection.
- **Every token minter hard-codes `query_needs: ['*']`.** These are login (`util/authentication.py`), API tokens (`models/alchemy/api_token/model.py`) and the render token (`routes/views/page_renderer.py`). So "superuser tokens ignore their query_needs" (WP-0c open item 5) is latent.
  **How to apply:** any WP that mints narrowed tokens (WP-5d scopes, WP-1h SEC-7) must wait for WP-4e's fix of `_compute_token_query_needs` and `SuperUserPermission`.
- **Login cookies ignore the JWT cookie config.** Login writes `accessKey` with a bare `set_cookie(..., httponly=True)`, while `unset_jwt_cookies` uses `JWT_COOKIE_DOMAIN`, `JWT_ACCESS_COOKIE_PATH`, `JWT_COOKIE_SECURE` and `JWT_COOKIE_SAMESITE`. Today all resolve to defaults (path `/`, no domain), so they match. If WP-5d sets the config only on one side, `/api/timeout` silently stops deleting the cookie.
- **Redirect hosts.** Werkzeug 0.16 makes the Location header absolute from the request's `Host`. There is no ProxyFix, so `X-Forwarded-Host` is ignored. nginx-proxy routes by VIRTUAL_HOST and has no proxy_cache. A Host-header redirect therefore only reflects back to the requester.
- **Before WP-0c the inactivity timeout signed no one out.** `/login` redirects any JWT-authenticated user straight back into the app. Count this as the baseline when judging session-lifetime changes.

Related: [[review-tooling-under-worktree-guard]]
