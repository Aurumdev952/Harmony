# 0006. Add WP-0k: links built from the request Host, and username matching at login

Status: applied by the lead on 2026-10-05, pending human ratification (SPEC section 10).

## Context

The WP-0i round-2 reviews (reviewer and security) found two pre-existing problems outside WP-0i's diff:

- **Links built from the request Host.** The password-reset link (`web/server/routes/views/admin.py:29`, reachable anonymously through `forgot_password`), the invite link (`web/server/routes/invite.py:19`), the access-granted email (`web/server/api/permission_api_models.py:268`) and the new-dashboard email (`web/server/api/dashboard_api_models.py:1098`) use `url_for(..., _external=True)` or the request Host directly. The app sets no `SERVER_NAME`, `ProxyFix` or trusted-hosts list. A forged `Host` (including `real.org:@attacker.invalid`, which nginx matches to the real vhost because `server_name` ignores the part after the colon) makes the app mail a link to the attacker's host. This is reset-link poisoning; it is exploitable wherever the proxy forwards the raw Host, which is unverified on nginx-proxy 1.11.6. WP-0i fixed the same mechanism for renders with a configured `DEPLOYMENT_BASE_URL`. `send_email` also mails a caller-supplied free-form `dashboardUrl` as the clickable link.
- **Username matching at login.** JWT login resolves usernames with `ILIKE` and `first()` (`web/server/security/signal_handlers.py:324` and flask-user's `find_user_by_username`), and the JWT identity is the submitted string rather than `user.username`. Verified on SQLite with the real lookup: the identity `john_doe@moh.gov.rw` loads `john.doe@moh.gov.rw`. A newly registered look-alike account is signed in as the older account with its roles and query policy.

## Decision

1. **WP-0k: Build outgoing links from the configured origin; match usernames exactly** is added to SPEC section 5: owner `backend`, supporting `security, qa`, depends on `0i`, Sec yes.
2. Rules:
   - Every link the server mails or returns (reset, invite, access granted, new dashboard, share by email, and any other `_external=True` or Host-derived URL) is built from `DEPLOYMENT_BASE_URL` through the helper WP-0i introduced; none reads the request Host or `SCRIPT_NAME`. `send_email` links to the dashboard's own page on the configured origin and ignores the caller's free-form URL.
   - Username lookups at login, registration and invitation compare on `lower(username)` for equality, never a pattern; the JWT identity is `user.username`.
3. Unit 1 verifies on a local stack whether nginx-proxy 1.11.6 forwards the raw Host; the result sets the severity recorded for the human.
4. INV-3 rows: the only outcome changes are 404 or 400 for requests that previously produced a poisoned link, and a login that previously matched the wrong account now matches none. WP-2b pins today's behaviour; WP-0k flips the pins in its own stack, by qa.

## Consequences

- SPEC 1.6: WP-0k row; phase 0 gains section 0k.
- WP-0i is not held for this; its carried risk F5 (free-form `dashboardUrl`) closes in WP-0k.
