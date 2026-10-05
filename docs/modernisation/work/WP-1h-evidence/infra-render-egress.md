# WP-1h infra: render-egress service and in-image renderer tests in CI

Date: 2026-10-05. Branch `mig/WP-1h-export-renderer-infra-2`, from `mig/WP-1h-export-renderer` at bbc0d81. Unit 1 is 0618f25 and unit 2 is f4c02e2.

## Unit 1: the `render-egress` service

### What changed against the snippet (`infra-request/compose.render-egress.yaml`)

| Snippet | Landed | Why |
|---|---|---|
| `depends_on: [render-egress]` | `condition: service_started` | Only map exports need the proxy. With the proxy stopped, a page without a map still renders (200), and a map page fails with 502 `egress_blocked` in 10.9 s, not at the deadline (below). Waiting for `service_healthy` would hold every export behind the proxy's health. |
| no `init` | `init: true` | Python as PID 1 ignores SIGTERM. Without an init, `docker stop` took 15.97 s, the 10 s timeout followed by SIGKILL. With one, it took 0.29 s. |
| proxy port only in the URL and healthcheck | `EGRESS_PROXY_PORT=3128` set explicitly | The test ties the renderer's `RENDERER_EGRESS_PROXY`, the proxy's port and the healthcheck together. |
| prod overlay not covered | `render-egress: restart: always` in `docker-compose.prod.yaml` | The renderer had it and the proxy did not. |
| anything else | kept as written | |

- **Dev overlay.** It needs no `build:` for `render-egress`. The renderer builds the shared image name. When Compose cannot pull an image that another service builds, it does not fail; it builds the image and both services use it. Checked with Compose v5.6.0 on a throwaway project.
- **The literal wording of the request.** "render-egress is the only service on both `render` and a network with a route out" is false as written, because `web` is on `render` and `default`. The test asserts the intent instead:
  - the services on `render` that have a route out are exactly `web` and `render-egress`;
  - the only route out for `render-egress` is its own `render-egress` network, which no other service joins, so it cannot reach redis or hasura on `default`;
  - the renderer is on `render` alone.

### Tests (`tests/infra/test_renderer.py`)

These run for every overlay: base, prod, dev and local.
- The renderer shares `render` only with web and the proxy.
- Only the proxy relays from `render` to a route out.
- Neither the renderer nor the proxy publishes a port.
- The proxy runs the renderer image with the `egress_proxy` entrypoint. It has a read-only root, `cap_drop: [ALL]`, no `cap_add`, `no-new-privileges`, `init`, 128 MiB of memory and 128 pids, and a healthcheck on its own port.
- The renderer's proxy URL matches the proxy's port, and both default the map origins to `https://api.mapbox.com`.
- One `RENDERER_MAP_ORIGINS` setting feeds both services.
- Prod restarts both.

Red on bbc0d81: 22 compose failures (27 with unit 2's tests). Green after the change. WP-0b's `test_compose.py` and `test_dockerfiles.py`: 50 passed. `docker compose config --quiet` exits 0 for base, prod, dev and local. In prod, only nginx publishes ports.

### Runtime check (local Compose, throwaway project `wp1h-infra2-egress`)

- **Setup.** The real `docker-compose.yaml`, with the renderer image built from this branch (`docker-compose.build.yaml`, `local/wp1h-infra2/harmony-renderer:egress`). A `/tmp` overlay pins subnets and replaces only `web`, with a fake on the same image. Port 5000 is the dashboard origin. Port 8000 is a map origin on the same host, which is the hard case: cookies are scoped to a host, not a port, so Chromium attaches the web origin's cookies to it. `RENDERER_MAP_ORIGINS=https://api.mapbox.com,http://web:8000`.
- **Container settings.**
  - `render-egress`: `ReadonlyRootfs=true`, `CapDrop=[ALL]`, `CapAdd=[]`, `Init=true`, `Memory=134217728`, `PidsLimit=128`, `no-new-privileges:true`, no port bindings, `healthy`.
  - The process runs as uid 1001 with `CapEff 0`, `CapBnd 0` and `NoNewPrivs 1`. A write to `/app` fails with `EROFS`.
  - `render` is `internal=true`. `render-egress` is `internal=false`. The renderer is on `render` only.

From inside the renderer container (`net_probe.py`):

```
"direct api.mapbox.com:443": "gaierror (no DNS)",
"direct 1.1.1.1:443": "OSError 101",
"direct 169.254.169.254:80": "OSError 101",
"direct redis:6379": "gaierror (no DNS)",
"direct render-egress:3128": "CONNECTED",
"proxy GET https://api.mapbox.com/styles/v1/mapbox/light-v10": "HTTP 401",
"proxy GET http://api.mapbox.com/styles/v1/mapbox/light-v10": "HTTP 403",
"proxy GET https://example.com/": "refused: Tunnel connection failed: 403 Forbidden",
"proxy GET https://events.mapbox.com/": "refused: Tunnel connection failed: 403 Forbidden",
"proxy GET http://169.254.169.254/latest/meta-data/": "HTTP 403",
"proxy GET http://redis:6379/": "HTTP 403",
"proxy GET http://web:8000/raw/style.json": "HTTP 200",
"proxy POST http://web:8000/raw/post": "HTTP 405",
"proxy CONNECT 169.254.169.254:443": "refused: Tunnel connection failed: 403 Forbidden"
```

The 401 is Mapbox's answer to a request with no access token, so a TLS session reached `api.mapbox.com` through the tunnel. The raw GET to `web:8000` carried `Cookie: accessKey=…` and `Authorization: Bearer …`. The map origin logged `"cookie": null, "authorization": null`.

**Cookies through the real renderer.** web asked the renderer for a PNG of a page that sets `webcookie`, loads a tile through `<img>`, and fetches a style with `credentials: 'include'` from `http://web:8000`. The result was `200 image/png 2727 B`, `Server-Timing: render;dur=1781`. Fake web log:

```
{"port": 5000, "path": "/dashboard", "cookie": "accessKey=eyJ…c2ln", "authorization": null}
{"port": 5000, "path": "/seen", "cookie": "accessKey=eyJ…c2ln; webcookie=set-by-the-page", "authorization": null}
{"port": 8000, "path": "/styles/light.json", "cookie": null, "authorization": null}
{"port": 8000, "path": "/tiles/1/2/3.png", "cookie": null, "authorization": null}
```

**Control.** The same render ran with `RENDERER_EGRESS_PROXY` pointed at a stand-in that forwards nothing and logs what Chromium sends it:

```
{"port": 3129, "path": "http://web:8000/styles/light.json", "cookie": "accessKey=eyJ…c2ln; webcookie=set-by-the-page", "authorization": null}
{"port": 3129, "path": "http://web:8000/tiles/1/2/3.png", "cookie": "accessKey=eyJ…c2ln; webcookie=set-by-the-page", "authorization": null}
```

So Chromium hands the proxy the render token and the page's cookie for a map origin on the web host. `render-egress` is what keeps them from leaving.

**Proxy log.** Every decision is logged with host and port only, never the path or query:

```
{"event": "egress", "host": "api.mapbox.com", "port": 443, "allowed": true}
{"event": "egress", "host": "api.mapbox.com", "port": 80, "allowed": false}
{"event": "egress", "host": "example.com", "port": 443, "allowed": false}
{"event": "egress", "host": "events.mapbox.com", "port": 443, "allowed": false}
{"event": "egress", "host": "169.254.169.254", "port": 80, "allowed": false}
{"event": "egress", "host": "redis", "port": 6379, "allowed": false}
{"event": "egress", "host": "web", "port": 8000, "allowed": true}
{"event": "egress", "host": "169.254.169.254", "port": 443, "allowed": false}
```

Over about 5 minutes, the healthcheck's TCP probes added no log lines.

**With the proxy stopped.**

| Proxy | Page | Result |
|---|---|---|
| up | map, ready only once its tile loads | 200 |
| up | no map | 200 |
| stopped | no map | 200 |
| stopped | map | 502 `{"error": "egress_blocked"}` after 10.90 s (grace 10 s; the deadline was 60 s) |

The project was removed with `docker compose down`, without `-v`.

## Unit 2: renderer tests inside the built image in CI

- **Script.** `docker/renderer/test_in_image.sh <image> [pytest args]` builds `docker/renderer/Dockerfile.test` on the given image.
  - `Dockerfile.test` adds hash-pinned pytest 9.1.1 (`docker/renderer/test-requirements.txt`, `--no-deps --require-hashes`) and keeps the working directory `/app`. Its context is limited to the pins file.
  - The script runs the suite with `--network none --read-only --tmpfs /tmp --tmpfs /home/pwuser --shm-size 1g --init --cap-drop ALL --cap-add SYS_CHROOT --security-opt no-new-privileges:true --security-opt seccomp=docker/renderer/seccomp_profile.json --memory 2g --pids-limit 512`.
  - Only `tests/worker/renderer` and `pyproject.toml` are mounted, read-only, so the code under test is the image's own (`/app/harmony/worker/renderer/egress_proxy.py`) and `.env` never enters the container.
  - The script fails if pytest reports any skip, because a skip here means the browser tests did not run.
- **Workflow (`.github/workflows/renderer.yml`).**
  - `pull_request` runs on changes to `harmony/worker/renderer/**`, `tests/worker/renderer/**`, `docker/renderer/**`, `pyproject.toml` and the workflow. The job builds and tests with `contents: read` only.
  - `push` to `main` and `workflow_dispatch` build, test, then push. The push is its own step after the tests, and the job has `packages: write`.
  - `permissions: {}` is set at the top. Actions are pinned by SHA, there is no `${{ }}` in `run:`, and concurrency cancels superseded PR runs.
- **Tests.** Each of these failed first and now passes:
  - every job builds, then tests, then (if it pushes) pushes;
  - PR jobs get a read-only token and never push;
  - the workflow triggers on renderer PRs;
  - a fake `docker` records the script's build and run arguments, which must include every hardening flag and exactly the two read-only mounts;
  - the script exits non-zero when pytest fails or reports a skip, in the normal and the `-q` summary format. A mutation of the skip check made the two skip cases fail;
  - `Dockerfile.test` installs only hash-pinned pytest.
- **Real run.** `docker/renderer/test_in_image.sh local/wp1h-infra2/harmony-renderer:egress -ra` gave `156 passed in 95.77s`, with all 25 tests in `test_render_browser.py` running and none skipped.
- **Static checks.**
  - actionlint 1.7.12, the release binary checked with `sha256sum -c`, with shellcheck 0.11.0: 0 findings. It does flag SC2086 and an untrusted `head_ref` on a deliberately bad workflow.
  - shellcheck on the script: clean.
  - zizmor 1.30.1 `--offline`: no findings, also with `--persona=auditor`. Each job is named, and `packages: write` carries an inline reason.
  - `docker build --check` on both renderer Dockerfiles: no warnings. `Dockerfile.test` skips `InvalidDefaultArgInFrom` on purpose: `RENDERER_IMAGE` has no default, so a missing image fails the build instead of pulling some other image.
  - A simulation of the `id: image` step under `bash -e` gives `ghcr.io/zenysis/harmony-renderer` with tag `main`, and `mig-WP-1h-export-renderer` for a branch.
- **Suites.**
  - `uv run --project ci/tools313 --locked pytest tests/infra`: 216 passed.
  - A trial merge with `mig/integration` merged cleanly and gave 219 passed.
  - ruff check and format: clean.
  - `uv lock --check --project ci/tools313`: ok. pyyaml 6.0.3 was added to the tools lane for the workflow tests; it ships cp313 wheels.

## Not shown

- A run on GitHub. The PR job runs once the branch is pushed. The first push to `main` after merge is the proof for the push job.
- A real Mapbox map, end to end. It needs a deployment's access token; the human request for a staging render stands.
