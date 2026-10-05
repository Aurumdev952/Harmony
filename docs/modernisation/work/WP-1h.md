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
      - tests/web/render/conftest.py
      - tests/worker/renderer/**
      - docs/modernisation/work/WP-1h.md
      - docs/modernisation/work/WP-1h-evidence/**
  - name: "core"
    files:
      - config/settings.py
      - tests/core/test_settings_render.py
  - name: "infra"
    files:
      - .github/workflows/renderer.yml
      - Makefile
      - docker-compose.yaml
      - docker-compose.build.yaml
      - docker-compose.dev.yaml
      - docker-compose.prod.yaml
      - docker/build.sh
      - docker/renderer/**
      - tests/infra/test_renderer.py
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
  - Egress and sandbox: see "Renderer threat model" below.
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

## Renderer threat model

Asset: the render token. While its render runs, it signs a browser in as a real user for one dashboard. Second asset: whatever the renderer's network position can reach, such as web's other routes, Redis, Postgres, Druid and cloud metadata.

The token is safe where the web app sends it. The web app builds the URL from `RENDER_WEB_ORIGIN` and `url_for`, never from the request (WP-0i N7, Host header). The renderer still treats the URL and the page as attacker-influenced, because a future caller could pass anything and a dashboard page loads tiles, maps and fonts it does not control.

| Threat | Control | Test |
|---|---|---|
| A render URL off the origin: another host, another port or scheme, `169.254.169.254`, an IPv6 literal (`[::1]`, `[fd00:ec2::254]`, `[::ffff:169.254.169.254]`), a hex IP, userinfo tricks (`http://web:5000@evil`, `http://evil@web:5000`), `file:`, `javascript:`, `data:`, or a scheme-relative URL | `parse_render_request` compares the parsed (scheme, host, port) with `RENDERER_ALLOWED_ORIGIN` and refuses userinfo (400). `browser.render` checks again before any browser starts. | `test_render_spec.py::test_only_the_allowed_origin_may_be_rendered`, `test_render_browser.py::test_render_refuses_a_spec_off_the_allowed_origin_without_a_browser` |
| The page loads sub-resources, fetches or navigates to another host, port, metadata IP or IPv6 literal, carrying the cookie (cookies are host-scoped, not port-scoped) | Layer 1: a context route aborts every HTTP request, navigation and redirect hop whose parsed origin is not exactly the allowed one (`egress.is_allowed`). Only `data:`, `about:blank` and same-origin `blob:` are let through. | `test_render_egress.py`, `test_render_browser.py::test_every_other_destination_is_blocked_and_recorded` |
| Connections that never become a routed HTTP request: WebSockets, `preconnect`, DNS prefetch, WebRTC | `context.route_web_socket` refuses every WebSocket. Layer 2: Chromium runs with `--proxy-server` set to an unresolvable proxy and a bypass list of `<-loopback>` plus the one origin, so the only direct connection it can open is to that origin; WebRTC is limited to proxied UDP and DNS prefetch is off. | `test_every_other_destination_is_blocked_and_recorded` (the second origin sees zero TCP connections), `test_the_proxy_fence_holds_even_if_the_request_guard_lets_everything_through` |
| A redirect from the origin to elsewhere, or the page navigating itself away | The route aborts the off-origin hop. `goto` errors become `PageFailed`. After load and again after the ready signal, the page must still be on the origin and the requested path. | `test_a_redirect_to_another_origin_fails_and_never_reaches_it`, `test_the_page_cannot_navigate_itself_to_another_origin` |
| Network egress if every in-browser control failed | Layer 3: the Compose `render` network is `internal: true`. The renderer is on that network only, and web is the only other service on it. | Unit 5 container check |
| A Chromium exploit from page content | Chromium keeps its sandbox (`chromium_sandbox=True`; Playwright's default would add `--no-sandbox`). The process runs as `pwuser` (uid 1001) with all capabilities dropped except `SYS_CHROOT`, `no-new-privileges`, a read-only root filesystem and Playwright's v1.63.0 seccomp profile. `SYS_CHROOT` stays only in the bounding set, so the zygote can chroot inside its own user namespace. The process itself holds no capability: `CapPrm` and `CapEff` are 0 and `CapBnd` is `0x40000`, read from `/proc/1/status` on the stack. Without it, Chromium's sandbox cannot start and renders fail. That profile is Docker's default plus `clone`, `setns` and `unshare`, which the namespace sandbox needs. Without the profile Chromium refuses to start, and the code has no `--no-sandbox` fallback. | `test_chromium_runs_with_its_sandbox` (it reads every Chromium process's flags from `/proc` during the render), plus the same test failing without the profile |
| One user's state leaking into the next render | A fresh browser per render, closed in `finally`. Service workers and downloads are blocked. | `test_nothing_from_one_render_survives_into_the_next` |
| The token in logs or error bodies | The sidecar logs one JSON line without the URL or token. Unexpected errors log only the exception type. Error bodies are a fixed code. The web side logs status, content type and size only. | `test_render_server.py::test_render_is_logged_as_one_json_line_without_the_token`, `::test_an_unexpected_failure_is_a_500_without_details`, `test_export_renderer.py::test_a_failed_render_is_logged_without_the_token` |
| Resource exhaustion | 16 KiB body cap, deadline (also Playwright's per-action default, so a slow page gets the whole deadline and no more), concurrency slots, output cap, page-height clip, Compose `init: true` (it reaps Chromium's orphaned helpers, which would otherwise pile up toward `pids_limit`), and Compose `mem_limit` and `pids_limit`. | `test_render_server.py`, `test_render_browser.py` |
| Token replay after the render | `render` claim liveness and a lifetime of deadline + 15 s (see Render token). | `test_render_tokens.py` |

Residual risks:
- The token is valid for any same-origin page while its render runs. It grants only `view_resource` on one dashboard under the user's own policy, so a hijacked page sees no more than the user could.
- Rootful Docker hosts that confine containers with AppArmor and restrict unprivileged user namespaces (such as Ubuntu 24.04 with `kernel.apparmor_restrict_unprivileged_userns=1`) are untested. If the sandbox cannot start there, Chromium refuses to launch and renders fail with a 500. They never fall back to `--no-sandbox`, so the failure is safe but visible.
- DNS rebinding of the origin host is out of scope: `web` resolves through Docker's embedded DNS on the internal network.

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

- [x] infra: add `docker/renderer/Dockerfile` (from `WP-1h-evidence/infra-request/Dockerfile`) and `docker/renderer/seccomp_profile.json` (from `infra-request/seccomp_profile.json`, Playwright v1.63.0, sha256 `cc3e61ca…7849`). Add the `renderer` service and the `render` network with `internal: true`, and on `web` set `RENDERER_URL`/`RENDER_WEB_ORIGIN` and `networks: [default, render]` (from `infra-request/compose.renderer.yaml`). Build and push the renderer image in CI next to web. Remove `URLBOX_API_KEY` from `docker-compose.yaml` (web and worker) and from `.env.example`. Verified locally in `WP-1h-evidence/unit-5-container-check.md`. This blocks deployments from using the renderer, but no WP-1h unit.
- [x] core: remove `URLBOX_API_KEY` and `RENDERBOT_EMAIL` from `config/settings.py` once this lands; nothing reads them after unit 3 (blocks nothing). Done on `mig/WP-1h-export-renderer-core`; see the 2026-10-04 core log line.
- [x] infra: also remove `RENDERBOT_EMAIL` from `docker-compose.yaml:143,178` and `.env.example:27` (the infra line above names only `URLBOX_API_KEY`; same as WP-0i's open infra request). No code reads either variable after the core change (blocks nothing). Done in `docker-compose.yaml`; for `.env.example` see the next line.
- [ ] human: remove the `URLBOX_API_KEY` and `RENDERBOT_EMAIL` lines from `.env.example`. Settings deny agents any read or edit of that file, including `grep` and `sed` (blocks nothing).
- [x] backend: in "Renderer threat model", change the Chromium row from "all capabilities dropped" to "all capabilities dropped except `SYS_CHROOT`", and add `init` to the resource-exhaustion row. Reasons and proof are in `WP-1h-evidence/infra-renderer-image.md` (blocks nothing).

## Log

- 2026-10-04 backend-8 unit 1: failing tests for tokens, routes and the sidecar; check: red on the base (missing `render_tokens`, `harmony.worker.renderer`, sidecar call).
- 2026-10-04 backend-8 unit 2: render tokens, liveness and policy-digest checks in `login_from_request` and `_install_token_needs`; check: `uv run pytest tests/web/render/test_render_tokens.py` 17 passed.
- 2026-10-04 backend-8 unit 3: web client for the sidecar (`render_dashboard`, `RenderedDashboard`), routes, thumbnail and email callers; check: `uv run pytest tests/web` 196 passed, 1 failed (pre-existing `flask_migrate` import in `test_graphql_endpoint_removed.py`).
- 2026-10-04 core (supporting, branch `mig/WP-1h-export-renderer-core`): removed `URLBOX_API_KEY` and `RENDERBOT_EMAIL` from `config/settings.py`; new `tests/core/test_settings_render.py` imports settings in a fresh interpreter with both variables set and asserts neither attribute exists. Check: red on e30587c (both names exposed), then `uv run pytest tests/core` 17 passed, `tests/web` 196 passed and 1 failed (the same pre-existing `flask_migrate` import), `tests/golden` 269 passed, ruff clean on the test (the two F401s on `config/settings.py:4` are pre-existing), mypy clean on both files. Tree grep for both names afterwards finds only `docker-compose.yaml`, `.env.example` (infra, requested above) and docs; `RENDERER_URL` and `RENDER_WEB_ORIGIN` stay read through `settings.getenv` in `page_renderer.py`, as the request asked for no new setting.
- 2026-10-04 backend-8 unit 4: renderer sidecar (`harmony/worker/renderer`: spec, egress guard, HTTP server, Playwright browser, hashed requirements). The worker tests were renamed `test_render_*.py` so their basenames stay unique. check: 88 passed in the image with `--network none`; host 275 passed, 1 skipped (browser), 1 pre-existing failure; black, ruff and mypy clean.
- 2026-10-04 backend-8 unit 4a (automated security review: egress bypass, SSRF, sandbox disabled): failing tests first. A WebSocket from the page reached another port on the origin host carrying the token (cookies ignore ports). A redirect raised a raw Playwright error. `render()` trusted its spec. Chromium ran with Playwright's default `--no-sandbox`. Fixes: `route_web_socket` refusal, a black-hole proxy with the origin as the only bypass, origin and path checks after load and after the ready signal, a pre-launch origin check, navigation errors as `PageFailed`, and `chromium_sandbox=True` with Playwright's seccomp profile. The threat model is recorded above. check: 7 new browser tests red, then 110 passed in the image (`--network none`, seccomp profile); without the profile Chromium refuses to start (sandbox test fails, no fallback); host 289 passed, 1 skipped, 1 pre-existing failure; black, ruff and mypy clean.
- 2026-10-04 backend-8 unit 5: infra request prepared (`infra-request/Dockerfile`, `compose.renderer.yaml`, `seccomp_profile.json`). check: the image builds from the pinned digest, runs as uid 1001 on a read-only root with the image HEALTHCHECK `healthy`, `/healthz` answers 200 from a peer, an off-origin render gets 400, and egress by IP and by name fails on an `--internal` network.
- 2026-10-04 infra (supporting, branch `mig/WP-1h-export-renderer-infra`, d6ef751 on e79b325): added `docker/renderer/{Dockerfile,Dockerfile.dockerignore,seccomp_profile.json}`, the `renderer` service on the internal `render` network, web's `RENDERER_URL`/`RENDER_WEB_ORIGIN`/networks, prod `restart`, a dev `build:`, the build overlay, `build.sh`, `make push` and `.github/workflows/renderer.yml`. `URLBOX_API_KEY` and `RENDERBOT_EMAIL` are removed from web and worker. Two changes from the proposal. First, `cap_add: [SYS_CHROOT]`: with `cap_drop: [ALL]` alone, Docker's rendering of the seccomp profile denies `chroot`, and every browser test fails at launch (13 failed). With the capability, 110 passed. Second, `init: true`: 6 zombies after 3 renders without it, 0 with it. The seccomp profile is byte-identical to Playwright v1.63.0 upstream. check: `tests/infra/test_renderer.py` 26 red on e79b325, then `tests/infra` 121 passed. A trial merge with `mig/integration` merged the infra files without conflicts, and its `tests/infra` gave 187 passed, including the WP-0b `test_compose.py` and `test_dockerfiles.py`. `docker compose config`, `docker build --check`, ruff, black and actionlint are clean. The image was built and run through Compose: healthy, uid 1001, `CapEff 0`, `/healthz` 200, off-origin 400, no egress, and a sandboxed Chromium printed a PDF. `.env.example` is left to the human because settings deny agent edits.
- 2026-10-04 backend-8 unit 6: end to end on the WP-2c stack with the renderer, a recording tap and a prebuilt client. Real PDF (A4, 1 page, 8,117 B), JPEG (1280x1024, 34,164 B) and PNG thumbnail (1280x1024, 15,486 B) came through the Flask routes in about 3 s each. The last token, reused after its render, gives 302 to login and a 401 from the API. A non-viewer gets 403 and an anonymous request gets 401, with no renderer call either way. The run found Playwright's 30 s per-action default cutting the 120 s deadline short; fixed test-first in 460b7f4 (111 passed in the image under the full Compose hardening). check: `WP-1h-evidence/unit-6-end-to-end.md`. Infra's branch is merged and the threat model is updated for SYS_CHROOT, `init` and untested AppArmor hosts.
- 2026-10-05 backend-8 unit 7 (resumed after the host reboot; the lost builder's uncommitted change and test were copied in and finished): `DashboardResource.read` counts a view through `record_dashboard_view`, which skips a request signed in with a live render token, so an export, thumbnail or emailed render no longer adds to `total_views`, `views_by_user` or `last_viewed` (WP-0i carried risk 5). The page's only view-counting call is `GET /api2/dashboard/<id>`; the other `track_dashboard_access` callers (`add_item`, `update`) need edit rights, which a render token never grants. Also drops the unused `SchedulerEntry` import (`app_base` registers the model), which CI's ruff set flags in a changed file. check: `tests/web/render/test_render_views.py` 2 failed on 6bb547e (no `record_dashboard_view`), then 2 passed; `uv run pytest tests/web` 199 passed, 1 failed (the pre-existing `flask_migrate` import); black 22.6.0 and ruff clean on the test.

## Evidence

- Unit 4: [WP-1h-evidence/unit-4-renderer-tests.md](WP-1h-evidence/unit-4-renderer-tests.md)
- Security review follow-up (unit 4a): [WP-1h-evidence/unit-4a-egress-and-sandbox.md](WP-1h-evidence/unit-4a-egress-and-sandbox.md)
- Unit 5: [WP-1h-evidence/unit-5-container-check.md](WP-1h-evidence/unit-5-container-check.md)
- Infra request (renderer image and Compose service): [WP-1h-evidence/infra-renderer-image.md](WP-1h-evidence/infra-renderer-image.md)
- Unit 6: [WP-1h-evidence/unit-6-end-to-end.md](WP-1h-evidence/unit-6-end-to-end.md), with outputs and harness in `WP-1h-evidence/e2e/`

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
