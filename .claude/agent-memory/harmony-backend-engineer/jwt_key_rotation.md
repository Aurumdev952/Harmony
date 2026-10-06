---
name: jwt-key-rotation
description: Rotating the JWT or session key breaks every request with an old accessKey cookie unless the request loader swallows InvalidSignatureError; JWT checks must not live in FlaskConfiguration
metadata:
  type: project
---

flask-jwt-extended 3.25 `verify_jwt_in_request_optional` only swallows a missing token. A cookie signed with a previous key raises `InvalidSignatureError`, which its error handler turns into a 422 on every request, `/login` included, and the cookie lives 365 days. Since WP-0b R3 (2026-10-04) `login_from_request` in `web/server/security/signal_handlers.py` treats a bad signature like an expired token (anonymous). Also, with an empty `JWT_SECRET_KEY` it silently signs with `SECRET_KEY`.

**Why:** WP-0b split `JWT_SECRET_KEY` from `DEFAULT_SECRET_KEY`. Without the loader fix, users could not reach the login page to get a new cookie.

**How to apply:** In the FastAPI `PrincipalDep` (C-5), make a bad signature mean anonymous (401 or redirect), never a 4xx/5xx on public pages. Keep JWT key checks where the JWT manager starts (`initialize_jwt_manager`), not in `FlaskConfiguration`: pipeline scripts build a `FlaskConfiguration` through `util/flask.py` and have no JWT key. See [[pipeline-builds-flask-app]] in core's memory.
