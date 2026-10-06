# WP-1h unit 8c: map exports, the egress proxy and fast failure

Date: 2026-10-05. Raised by the interrogate panel (Opus and Sonnet) and made an INV-1 blocker by the lead.

## The regression

Every base map style in `web/client/components/ui/visualizations/MapCore/defaults.js` is `mapbox://styles/...`, which loads from `api.mapbox.com`. The screenshot app sets `#dashboard-load-success` only after `waitForMapboxMapLoad` resolves, and that needs the style. With the egress fence of units 4 and 4a, a dashboard with a map therefore waited out the 120 s deadline and failed, where urlbox rendered it.

## The fix (option (a) from the lead)

- **Map origins.** `RENDERER_MAP_ORIGINS` (default `https://api.mapbox.com`) lists bare origins. The page may fetch them, but never navigate to them. They are reachable only through the egress proxy. Without `RENDERER_EGRESS_PROXY`, the list is dropped at startup, so nothing but the dashboard origin is reachable.
- **Egress proxy.** `harmony/worker/renderer/egress_proxy.py` is stdlib only and runs from the renderer image as its own service. It sits on `render` and on a network with a route out; the renderer stays on `render` (internal) only.
  - It tunnels CONNECT only to an allowed https origin.
  - It relays a plain GET or HEAD only from an allowed http origin, with `Cookie`, `Authorization`, `Host` and hop-by-hop headers dropped.
  - Everything else gets 403 before any connection is made.
  - It logs one JSON line per decision, with host and port but never the path or query, because map access tokens travel in the query.
- **Chromium.** Its proxy is now the egress proxy instead of the black hole. The bypass list (the dashboard origin only) is unchanged, so every other connection, including preconnects, goes through the proxy's allowlist. WebSockets are still refused.
- **The cookie.** The `accessKey` cookie is host-only for the dashboard origin, so Chromium never attaches it to a map request. The proxy also drops `Cookie` and `Authorization`, so neither the cookie nor the render token can leave through it.
- **Fast failure.** Once the page needs something it cannot get, it has `RENDERER_BLOCKED_GRACE_SECONDS` (default 10) left to signal ready. After that, the render fails with 502 `egress_blocked` naming the hosts, instead of waiting out 120 s. Four things count as needing something it cannot get:
  - a request the guard refuses;
  - a refused WebSocket;
  - a map request that fails at the proxy (CORS failures included);
  - a map response of 400 or more, other than 404, which is a tile outside the map's coverage.

  Refusing a host in `RENDERER_IGNORED_BLOCKED_HOSTS` (default `events.mapbox.com`, Mapbox telemetry) does not start the grace period.

## Tests

Inside the renderer image, `--network none --read-only --tmpfs /tmp --cap-drop ALL --cap-add SYS_CHROOT --init` with the seccomp profile:

```
docker run --rm --network none --security-opt seccomp=docker/renderer/seccomp_profile.json \
  --cap-drop ALL --cap-add SYS_CHROOT --init --read-only --tmpfs /tmp \
  -v <worktree>:/src:ro harmony-renderer-test:wp1h tests/worker/renderer -q
155 passed in 98.18s
```

New browser tests. The map origin is a local server named `localhost`, so it is a different host from the dashboard's `127.0.0.1`; a cookie is host-scoped, so this proves it is not sent.

| Test | Shows |
|---|---|
| `test_a_map_loads_its_style_and_tiles_through_the_egress_proxy` | The style and a tile load through the proxy, the page signals ready, and both map requests carry no cookie. |
| `test_a_map_needing_a_host_off_the_list_fails_fast_not_at_the_deadline` | The render fails with `EgressBlocked` naming `styles.invalid` in under 10 s with a 20 s deadline (grace 1 s). |
| `test_an_unreachable_map_origin_fails_fast` | The proxy answers 502 for a closed port, and the render fails fast. |
| `test_without_an_egress_proxy_a_map_fails_fast` | With no proxy configured, a map fails fast instead of hanging. |
| `test_refused_telemetry_does_not_fail_a_page_that_loads` | A refused `events.mapbox.com` beacon does not fail a page that signals ready 2.5 s later, past a 1 s grace. |
| `test_the_page_cannot_navigate_to_a_map_origin` | The map origin receives no request. |
| `test_the_egress_proxy_holds_even_if_the_request_guard_lets_everything_through` | With the guard patched to allow everything, the second origin sees zero requests and zero connections. |

On the host (no Playwright), `uv run --locked pytest tests/worker/renderer`: 131 passed, 1 skipped (the browser file). This includes:
- `test_render_egress_proxy.py`: CONNECT allowlist; another port, another name for the same address, the metadata IP and `[::1]` refused without connecting; https refused for an http-only origin; credentials dropped; POST, origin-form and bodies refused; the decision log has no path or query;
- `test_render_egress.py`: map origins are exact and never navigable; origin-list parsing;
- `test_render_settings.py`: no proxy means no map origins.

## Container check (egress from the internal network)

The proxy ran from the renderer image (`--read-only --cap-drop ALL --security-opt no-new-privileges`) on an `--internal` network and on a network with a route out, with `EGRESS_ALLOWED_ORIGINS=https://api.mapbox.com`. A probe container ran on the internal network only:

```
"direct api.mapbox.com:443": "gaierror",
"direct 1.1.1.1:443": "OSError",
"proxy https://api.mapbox.com/styles/v1/mapbox/light-v10": "HTTP 401",
"proxy https://example.com/": "refused: Tunnel connection failed: 403 Forbidden",
"proxy https://events.mapbox.com/": "refused: Tunnel connection failed: 403 Forbidden",
"proxy http://169.254.169.254/latest/meta-data/": "HTTP 403"
```

The 401 is Mapbox's own answer to a request without an access token. It shows that a real TLS session reached `api.mapbox.com` through the tunnel. Proxy log:

```
{"event": "egress", "host": "api.mapbox.com", "port": 443, "allowed": true}
{"event": "egress", "host": "example.com", "port": 443, "allowed": false}
{"event": "egress", "host": "events.mapbox.com", "port": 443, "allowed": false}
{"event": "egress", "host": "169.254.169.254", "port": 80, "allowed": false}
```

## Not shown

A real Mapbox map has not been rendered end to end. That needs a deployment's Mapbox access token, which agents do not have; the disposable stack has none. The human or infra should render a dashboard with a map tile on a staging deployment once `render-egress` is deployed (see the WP Requests).
