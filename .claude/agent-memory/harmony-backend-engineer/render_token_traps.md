---
name: render-token-traps
description: WP-1h render tokens and the renderer sidecar: origin rules, the single fingerprint, cache-key traps in tests, merging WP-0i, lint on pre-WP-2f branches
metadata:
  type: project
---

Facts from WP-1h (2026-10-05) that are not obvious from one file:

- **Two origins, never mixed.** Renders load `RENDER_WEB_ORIGIN` (internal, default `http://web:5000`, the renderer's only allowed origin). Links sent to people use `DEPLOYMENT_BASE_URL` (`deployment_dashboard_url`). A merge that "unifies" them breaks either the renderer fence or emailed links.
- **One fingerprint.** `signal_handlers.query_policy_fingerprint` is both the thumbnail cache key and the render token's `policy` pin. It must be computed from the request identity *before* `_install_token_needs` replaces `identity.provides` (Flask-Principal sets `g.identity` before `identity_loaded`), so on page load it is the account digest and at request time it is the caller's (possibly narrowed) digest. A narrowed API token therefore fails closed by design.
- **Test caches see render-token keys.** `render_token` writes `render-token:<id>` into `app.cache`, so a test that unpacks "the one cache key" must filter on `thumbnail:`.
- **Lint.** A branch without `[tool.ruff]` makes `uvx ruff` pick up some unrelated config (SIM/DTZ/UP rules). After integration is merged, use `bash ci/lint_python.sh mig/integration` and `uv run --locked mypy`. See [[post-wp2f-tooling]].

**Why:** the WP-0i merge into WP-1h had six conflicts in exactly these places.
**How to apply:** when touching the render path or FastAPI's `PrincipalDep` render-claim handling (WP-5a/5f), keep these invariants and their tests (`tests/web/render/test_render_origin.py`, `test_render_tokens.py`).
