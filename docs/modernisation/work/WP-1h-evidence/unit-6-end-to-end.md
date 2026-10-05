# WP-1h unit 6: end to end on the disposable stack

Date: 2026-10-04. The stack is WP-2c's `tests/contract/stack` (Postgres, Redis, Hasura, the Druid stub, Mailpit, web on gunicorn, a loopback forwarder) running the WP-1h tree at e79b325 plus the timeout fix. All services sit on the stack's internal network, which has no route out. Overlay files are in `e2e/`:

- `compose.renderer.yaml` adds:
  - `renderer`: image built from `infra-request/Dockerfile`, hardened like the infra Compose service (read-only, cap_drop ALL with SYS_CHROOT, no-new-privileges, the seccomp profile, uid-owned home tmpfs);
  - `render-tap`: a test-only pass-through between web and the renderer that records each request body, so the check can reuse a token after its render;
  - `webpack-static`: dev-mode Flask proxies `/build/*` to `localhost:8080`, so this serves a prebuilt client there, in web's network namespace.
- web is set to `RENDERER_URL=http://render-tap:8080` and `RENDER_WEB_ORIGIN=http://web:5000`.
- `wp1h_spec.py` prints a complete latest-version dashboard spec with one text tile. It runs inside the web container.
- `e2e_check.py` does the checks below through the forwarder on 127.0.0.1. It never prints a password or a token.

## Results (`e2e/wp1h-e2e-report.json`)

| Check | Result |
|---|---|
| Create dashboard `wp1h-render-check-3` (`POST /api2/dashboard`, admin) | 200 |
| `GET /dashboard/<slug>/pdf` | 200 `application/pdf`, 8,117 bytes, 1 page, MediaBox 595.92 x 842.88 pt (A4), 4.0 s |
| `GET /dashboard/<slug>/jpeg` | 200 `image/jpeg`, 34,164 bytes, 1280 x 1024 px (full page, which fits the viewport), 3.4 s |
| `GET /dashboard/<slug>/png/thumbnail` | 200 `image/png`, 15,486 bytes, 1280 x 1024 px, 3.1 s |
| URLs the renderer was asked to load | `http://web:5000/dashboard/<slug>?screenshot=1&pdf=1`, `...?screenshot=1`, `...?screenshot=1&thumbnail=1`, each with `timeout_seconds` 120 |
| The last render's token reused after its render | dashboard page `302 -> /login?next=/dashboard/<slug>`; `GET /api2/dashboard` `401` |
| A signed-in user without view on the dashboard requests the PDF | 403, renderer calls made: 0 |
| Anonymous request for the PDF | 401, renderer calls made: 0 |
| Renderer log | `{"event": "render", "format": "pdf", "bytes": 8117, "blocked_hosts": [], "duration_ms": 2229, "status": 200}`, and the same shape for jpeg and png |
| Renderer process capabilities (`/proc/1/status`) | `CapPrm 0`, `CapEff 0`, `CapBnd 0x40000` (SYS_CHROOT only) |

The outputs are `e2e/pdf.pdf`, `e2e/jpeg.jpeg` and `e2e/png_thumbnail.png`. All three show the dashboard's text tile, rendered with the app's own fonts and layout.

Timing: about 2.3 s of render time per export. urlbox added a fixed 10 s delay to every PDF on top of its wait.

## Found on the way

- **Playwright's 30 s per-action default cut renders short of the 120 s deadline.** The first runs failed with `TimeoutError` at 30.9 s. Fixed test-first in 460b7f4 (`test_a_slow_page_gets_the_whole_render_deadline`, red at 31 s, green after `context.set_default_timeout`).
- **`cap_drop: [ALL]` alone stops the sandboxed Chromium from launching** (`TargetClosedError`). It needs `SYS_CHROOT` in the bounding set. Infra found the same and added `cap_add: [SYS_CHROOT]` to the Compose service. The in-image suite passes under the full hardening: `--read-only --tmpfs /tmp --tmpfs /home/pwuser:uid=1001,gid=1001,mode=0700 --cap-drop ALL --cap-add SYS_CHROOT --security-opt no-new-privileges:true --security-opt seccomp=...` gives 111 passed.
- The `app.cache` registration of the render id must be shared by every gunicorn worker. It is: Flask-Caching uses Redis whenever `REDIS_HOST` is set, which every Compose deployment sets. A deployment without Redis and with several worker processes would refuse render tokens in the other workers, and those renders would fail (fail closed).

## Not covered here

- Dashboards with query tiles. The Druid stub has no data for a chart, so the tile-loaded path (`waitForVisualizationDataToLoad`) is not exercised. The text tile does exercise the ready signal (`#dashboard-load-success`) end to end.
- The visual comparison against urlbox output that phase 1 asks for. urlbox cannot be called from tests (SPEC), so no reference images exist here.
