---
wp: "1h"
title: "Self-hosted export renderer"
status: building
owner_role: "backend"
instances:
  - name: "backend-8"
    files:
      - web/server/routes/views/page_renderer.py
      - web/server/routes/page_renderer.py
      - web/server/security/render_tokens.py
      - web/server/security/signal_handlers.py
      - web/server/redis/thumbnail_storage_service.py
      - web/server/routes/views/dashboard.py
      - web/server/api/dashboard_api_models.py
      - tests/web/render/fakes.py
      - tests/web/render/test_render_route_guards.py
      - harmony/worker/renderer/**
      - tests/web/render/test_export_renderer.py
      - tests/web/render/test_render_tokens.py
      - tests/worker/renderer/**
      - docs/modernisation/work/WP-1h.md
      - docs/modernisation/work/WP-1h-evidence/**
branch: "mig/WP-1h-export-renderer"
requirements: [SEC-7, SEC-9, SEC-10]
contracts_consumed: []
contracts_changed: [C-5]
security_review: true
---

# WP-1h: Self-hosted export renderer

Phase 1 section 1h; 03-target-architecture (render path); decision 0004. Builds on WP-0i (`mig/WP-0i-render-route-guards`, backend-7), which is merged into this branch: WP-0i owns the route-level authorisation and the thumbnail cache key; this WP replaces urlbox.io behind the same routes.

## Design

- **Renderer sidecar** (`harmony/worker/renderer/`, run as `python -m harmony.worker.renderer`). A stdlib `ThreadingHTTPServer` with one endpoint, `POST /render`, plus `GET /healthz`. Its only dependency is Playwright. The digest-pinned `mcr.microsoft.com/playwright/python:v1.63.0-noble` base image ships Chromium and its libraries but not the Python package, so the image installs `playwright==1.63.0` and its three dependencies from `harmony/worker/renderer/requirements.txt` with `--require-hashes --no-deps`.
  - Every render launches a fresh Chromium and closes it afterwards, so no cookie, cache or storage outlives one user's render.
  - It sets the `accessKey` cookie for the one allowed origin and loads the dashboard URL. It waits for `#dashboard-load-success`, the tiles-loaded signal the screenshot app already emits; urlbox's extra fixed 10 s PDF delay is dropped. It then returns PDF, PNG or JPEG bytes.
  - Egress: the request URL must be on `RENDERER_ALLOWED_ORIGIN` (`http://web:5000`). A route guard aborts every browser request to any other origin, and records the blocked hostnames for WP-7g. Service workers and downloads are blocked. The Compose network is `internal: true`, so the container has no route out even if the guard failed.
  - Limits: the request body is at most 16 KiB. The deadline is the requested timeout, capped by `RENDERER_MAX_TIMEOUT_SECONDS` (default 120) and enforced with `asyncio.wait_for` around the whole render, and the browser is closed in `finally`. Output is capped by `RENDERER_MAX_BYTES` (default 25 MiB), and full-page captures are clipped at `RENDERER_MAX_PAGE_HEIGHT` px. `RENDERER_CONCURRENCY` (default 2) limits concurrent renders; a request that cannot get a slot before its deadline gets 503.
  - Metrics: a JSON log line per render (`event=render`, format, status, `duration_ms`, bytes, blocked hosts), and a `Server-Timing: render;dur=<ms>` header that the web app logs as well.
- **Web side** (`web/server/routes/views/page_renderer.py`). The urlbox call becomes `POST {RENDERER_URL}/render` with JSON `{url, token, format, viewport, full_page, pdf, timeout_seconds}`.
  - The URL is `RENDER_WEB_ORIGIN` plus the `url_for` path. It never uses the request's Host header, so a forged Host can no longer send the token elsewhere.
  - The response is checked for status, content type and size. Callers get `RenderedDashboard(content, content_type)` or `None`. The routes keep their URLs, auth (WP-0i) and content types: `application/pdf`, `image/png` and `image/jpeg`.
  - The routes pass `width`, `height`, `full_page`, `pdf_page_size` and `pdf_orientation` from the request args; a value outside the renderer's ranges falls back to the default. The other urlbox args (`delay`, `wait_timeout` and so on) are gone. Thumbnails and emailed renders take no args (before, an emailed render read the share request's args).
- **Render token** (`web/server/security/render_tokens.py`, SEC-7).
  - It is an HS256 `accessKey` JWT in the existing flask-jwt-extended 3 layout. `identity` is the requesting user, never a bot. `needs` is `[["view_resource", <resource_id>, "dashboard"]]`.
  - `query_needs` stays `['*']`, so each page request resolves the account's own policy. When the caller renders as themselves (the routes and the thumbnail), a `policy` claim pins the digest of their policy at request time (`query_policy_fingerprint`, the thumbnail cache key). If the account's digest differs when the page loads, `_install_token_needs` grants nothing, so a policy change during the render fails the render instead of widening it or caching it under the old key (WP-0i carried risk 2). A caller signed in with a narrowed API token pins the narrowed digest, which the account's digest never matches, so that render fails closed. Emailed renders run as the recipient, so no digest is pinned and the recipient's account decides.
  - It carries a `render` claim holding a random id that is registered in `app.cache` for the render's lifetime and deleted when the renderer returns. `login_from_request` refuses a render token whose id is no longer live. The token is therefore usable for exactly one render: short-lived (deadline + 15 s) and single-use per render.
  - The browser needs it for every request the page makes, so "single use" means one render, not one HTTP request.
- **Deferred to WP-5f:** moving renders to a Celery `exports` queue with `RenderJob` rows and `202 {job_id}` (phase 1h data structure; WP-0i carried risk 4). That changes the client contract (download links, `ThumbnailStorageService`), so it lands with the FastAPI export port and frontend-platform. The sidecar API is the same one a Celery task would call.
- **INV-7:** the renderer replaces the urlbox SaaS, which 03-target-architecture counts as a service that leaves the stack, so the count stays the same. Flagged for the reviewer.

## Plan

1. Failing tests: `tests/web/render/test_render_tokens.py` covers minting, claims, liveness, refusal after the render and expiry. `tests/web/render/test_export_renderer.py` covers: the route calls the renderer with the internal URL and a live token and never an external host, even with a forged Host header; timeout, error, wrong content type and oversize all give a failure; content types; a restricted user's token carries their policy and never a wider one. `tests/worker/renderer/` covers request validation, the egress guard and the HTTP server with a fake browser. Check: they fail on the base for the stated reasons.
2. Render tokens plus the `login_from_request` check. Check: `tests/web/render/test_render_tokens.py` green.
3. Web client for the sidecar; callers updated; WP-0i fakes swapped from urlbox to the sidecar. Check: `uv run pytest tests/web` green apart from the pre-existing `flask_migrate` import failure.
4. The renderer sidecar. Check: host tests green; browser tests (`tests/worker/renderer/test_render_browser.py`) green inside the renderer image against a local origin, covering cookie, ready signal, blocked egress, timeout, size cap and redirect to login.
5. Infra request: the exact `docker/renderer/Dockerfile`, Compose service and internal network, prepared under `WP-1h-evidence/infra-request/` and built locally. Check: the image builds from the pinned digest, runs as non-root, `/healthz` answers, and egress from the container fails.
6. End to end on the disposable stack (WP-2c `tests/contract/stack` plus the renderer): real PDF, PNG and JPEG through the Flask routes for a seeded dashboard, with pixel dimensions and byte sizes recorded, a second use of the token refused, and a non-viewer refused. Check: evidence file.
7. Render page loads stop counting as dashboard views (WP-0i carried risk 5). Check: unit test.
8. `pstack:interrogate` on the token and the renderer, then deslop, then review. Check: findings addressed; status `review`.

## Contract changes

C-5 (session and JWT format, owned by backend). Old: a render token was a plain `accessKey` JWT (`needs`, `query_needs: ['*']`) valid for 120 s. New: two optional `user_claims`, `render` (a random id that must be live in `app.cache`) and `policy` (a sha256 hex digest). Consumers: Flask `login_from_request` and `_install_token_needs` (this WP), and the FastAPI `PrincipalDep` (WP-5a/5f, backend). Ordinary session and API tokens carry neither claim and are unchanged. The `PrincipalDep` must refuse a token with a `render` claim whose id is not live, and apply the `policy` check, until the renderer signs in through FastAPI.

## Requests

- [ ] infra: `docker/renderer/Dockerfile`, the `renderer` Compose service on an `internal: true` network, `RENDERER_URL`/`RENDER_WEB_ORIGIN` on `web`, and removal of `URLBOX_API_KEY` from `docker-compose.yaml` and `.env.example`. The exact files will be under `WP-1h-evidence/infra-request/` (blocks unit 5's merge, not its local build).
- [ ] core: remove `URLBOX_API_KEY` and `RENDERBOT_EMAIL` from `config/settings.py` once this lands; nothing reads them after unit 3 (blocks nothing).

## Log

- 2026-10-04 backend-8 unit 1: failing tests for tokens, routes and the sidecar; check: red on the base (missing `render_tokens`, `harmony.worker.renderer`, sidecar call).
- 2026-10-04 backend-8 unit 2: render tokens, liveness and policy-digest checks in `login_from_request` and `_install_token_needs`; check: `uv run pytest tests/web/render/test_render_tokens.py` 17 passed.
- 2026-10-04 backend-8 unit 3: web client for the sidecar (`render_dashboard`, `RenderedDashboard`), routes, thumbnail and email callers; check: `uv run pytest tests/web` 196 passed, 1 failed (pre-existing `flask_migrate` import in `test_graphql_endpoint_removed.py`).
- 2026-10-04 backend-8 unit 4: renderer sidecar (`harmony/worker/renderer`: spec, egress guard, HTTP server, Playwright browser, hashed requirements). The worker tests were renamed `test_render_*.py` so their basenames stay unique. check: 88 passed in the image with `--network none`; host 275 passed, 1 skipped (browser), 1 pre-existing failure; black, ruff and mypy clean.

## Evidence

- Unit 4: [WP-1h-evidence/unit-4-renderer-tests.md](WP-1h-evidence/unit-4-renderer-tests.md)

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
