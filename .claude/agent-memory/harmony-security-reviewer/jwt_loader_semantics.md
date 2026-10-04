---
name: jwt-loader-semantics
description: Why swallowing JWT decode errors in login_from_request yields no identity (flask-jwt-extended 3.25.1), and what to re-check for the FastAPI auth dependency (C-5)
metadata:
  type: reference
---

flask-jwt-extended 3.25.1 (`verify_jwt_in_request_optional`) sets `ctx_stack.top.jwt` (the *app* context) only after `_decode_jwt_from_request` succeeds; `get_jwt_identity`/`get_jwt_claims` read that attribute. So catching `ExpiredSignatureError`/`InvalidSignatureError` leaves identity `None`, claims `{}`, and no user lookup. Only `expired_jwt` differs for expired tokens, and nothing in Harmony reads it. Headers are tried before cookies, and a bad header token ends the search: it never borrows the cookie's identity. `alg: none`, HS512 and malformed tokens still raise (422).

This relies on a fresh app context per request. Under gunicorn with gevent, werkzeug's Local is greenlet-scoped and nothing pushes a long-lived app context (checked 2026-10-04). Re-check if anything adds `app.app_context().push()`.

**How to apply:** For the FastAPI `PrincipalDep` (C-5), require the same properties: a bad or expired signature means anonymous, no partial claims, the algorithm pinned to HS256, and an identical response for expired and forged tokens. The probe pattern (drive the real loader with forged, tampered, alg-confused and expired tokens via `test_request_context`, with `Transaction` monkeypatched) took 8 cases and about 1 second on py3.8.
