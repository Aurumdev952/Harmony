# 0009. WP-1h: the export renderer and render-egress as stack services (INV-7)

Status: applied by the lead on 2026-10-05, pending human ratification (SPEC section 10).

## Context

INV-7 says the stack never gains a long-running service without losing one. The target architecture (03-target-architecture.md) placed export rendering "in a Celery worker", and the phase-1 text for 1h described a Celery task driving Chromium. WP-1h built something different, and its code reviewer asked for a decision rather than a waiver:

- **`renderer`**: a sidecar that runs headless Chromium behind a stdlib HTTP server, with no published ports, a read-only root, seccomp, `cap_drop ALL`, pids and memory limits, and an egress fence that lets the browser reach only `RENDER_WEB_ORIGIN`. It renders one dashboard per single-use token (SEC-7).
- **`render-egress`**: a small forward proxy that is the only path from the renderer to the map tile origins, and strips `Cookie` and `Authorization` on the way (SEC-10).
- **What leaves:** the urlbox SaaS (dashboard content no longer sent to a third party), the `URLBOX_API_KEY` secret, the render bot account and its 365-day sessions, and the `RENDERBOT_EMAIL` setting.

The reviewer's point stands: urlbox was never a container, so the stack has two more long-running processes than before and none fewer.

## Decision

1. **The renderer stays a separate service.** Chromium must not run inside the web or Celery worker image: those images hold the Postgres credentials, the Druid connection and the application secrets, and the sandbox and egress fence depend on the renderer having none of them. Folding the browser into the worker would trade the SEC-10 control for INV-7 bookkeeping. The Celery move in WP-5f puts the *job* (queueing, retries, the `RenderJob` record) in the worker; the browser process stays in the sidecar, which the worker calls over the Compose network.
2. **`render-egress` is time-boxed to WP-7g.** It exists only because maps still load from Mapbox. WP-7g (MapLibre with self-hosted tiles) retires it, and WP-7g's definition of done includes removing the service and its Compose entry. A test in `tests/infra` fails if the service is still defined once WP-7g is `done`.
3. **INV-7 accounting.** The renderer counts against Hasura, which WP-5c retires; until then the stack is one service over the invariant, recorded here rather than silently. Phase 5 may not add any further long-running service.
4. **Text corrections.** 03-target-architecture.md and the phase-1 1h section are corrected to "self-hosted Playwright in a sandboxed renderer sidecar, dispatched from the Celery worker after WP-5f". The remaining WP-1h findings (fail-fast clock on iframe tiles, hung-Chromium slot leak, cap below concurrency, mypy strict on `harmony/worker`, pin tests through a real page load) are backend work on the WP and not part of this decision.

## Consequences

- WP-1h may go `ready` once its reviewer, QA and security gates approve the remaining findings; INV-7 no longer blocks it.
- WP-5f carries the job move; WP-7g carries the `render-egress` removal with its failing-first test.
- The human ratifies or overturns this with the other pending decisions; overturning means WP-1h rebuilds the renderer inside the worker image and the security review of that image is redone.
