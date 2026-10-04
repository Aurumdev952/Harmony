---
name: wp-0c-findings
description: Non-obvious facts about raw Druid query paths, session persistence and /api/timeout found during WP-0c (2026-10-04); relevant to WP-4e authz and WP-5d identity
metadata:
  type: project
---

- `/api/timeout` is live. `web/client/util/timeoutSession.js` POSTs it through ZenClient (`/api/<path>`). It is the server half of the automatic sign-out. Do not delete it as "unused".
  **Why:** WP-0d had it on its delete list, and the lead removed it on 2026-10-04.
  **How to apply:** grep `web/client` for `ZenClient.post('<name>'` before calling any `/api/*` route dead.
- `app.query_client` is the user-scoped `AuthorizedQueryClient`. `app.system_query_client` and every `druid_context` component (time boundary, row count, dimension metadata) use the unwrapped system client, which applies no policy.
  **Why:** SEC-4. WP-0c removed `AuthorizedQueryClient.run_raw_query`, which had no callers. User input still reaches system-client raw queries through `/api/field/<ids>` (FieldsApi: row count and time boundary per field, cached per field and shared across users).
  **How to apply:** in WP-4e, decide whether field summaries take the `Principal`'s filter. If they do, the cache key must include the policy hash (C-9 rule).
- In WP-0c, "remember me" persistence became a signed `user_claims.remember_me` claim in the `accessKey` JWT, read by `is_session_persisted`.
  **Why:** browsers never send a cookie's expiry, and both login kinds issue 365-day tokens.
  **How to apply:** C-5 (backend) must carry this claim forward into `harmony/core/authz/tokens.py`.

- Never forward `request.args` into Flask 1.0's `url_for`. Keys such as `_external` and `_scheme` let a link choose the redirect host, and `endpoint` or `_method` cause 500s.
  **Why:** an interrogate reviewer found this open redirect in the first WP-0c patch. Fixing the BuildError had made the line reachable.
  **How to apply:** when you fix a dead line, re-check what that line exposes once it runs.
- `/api/timeout` logs out Flask-Login but never clears `accessKey`, so the 365-day JWT signs the user straight back in. The inactivity timeout is only a client-side redirect. This was routed to the lead on 2026-10-04.

Related: [[running-legacy-python-tests]]
