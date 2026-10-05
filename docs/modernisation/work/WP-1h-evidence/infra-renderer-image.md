# WP-1h infra: renderer image and Compose service

Date: 2026-10-04. Branch `mig/WP-1h-export-renderer-infra`, commit d6ef751, based on e79b325.

## Files

- `docker/renderer/Dockerfile`: the proposal, plus a digest-pinned `# syntax=` line (the same frontend pin as integration). `requirements.txt` is bind-mounted into the `pip install` step instead of copied and deleted. The code is copied with `COPY --link` and stays root-owned.
- `docker/renderer/Dockerfile.dockerignore`: the build context is `harmony/worker/renderer` only, 23.6 kB. The root `.dockerignore` does not exclude `.env` on this branch.
- `docker/renderer/seccomp_profile.json`: byte-identical to `https://raw.githubusercontent.com/microsoft/playwright/v1.63.0/utils/docker/seccomp_profile.json` (both sha256 `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`).
- `docker-compose.yaml`: adds the `render` network (`internal: true`) and the `renderer` service. web gets `RENDERER_URL`, `RENDER_WEB_ORIGIN` and `networks: [default, render]`. `URLBOX_API_KEY` and `RENDERBOT_EMAIL` are removed from web and worker. The worker does not render: every caller of `render_dashboard` runs in a Flask request.
- `docker-compose.prod.yaml`: `restart: always` for the renderer, as for the other services. `docker-compose.dev.yaml`: a `build:` for the renderer, so `make up DEV=1` builds it instead of pulling it. `docker-compose.build.yaml`, `docker/build.sh` and `make push` build and push it next to web.
- `.github/workflows/renderer.yml`: builds and pushes `ghcr.io/<owner>/<repo>-renderer:<ref>` on push to main and on manual dispatch. It uses the same pinned actions and least-privilege `permissions` as integration's `web.yml`. The ref is converted to a valid image tag, because `mig/...` branch names contain `/`.
- `tests/infra/test_renderer.py`: 25 tests.

## Changes from the proposal

| Change | Why | Proof |
|---|---|---|
| `cap_add: [SYS_CHROOT]` | Docker applies the seccomp profile's capability rules against the container's own capabilities. The profile allows `chroot` only with `CAP_SYS_CHROOT`, so with `cap_drop: [ALL]` alone Chromium's zygote dies with `Check failed: sys_chroot("/proc/self/fdinfo/") == 0` and every render fails. Unit 5 never launched a browser under `--cap-drop ALL`, and unit 4a never dropped capabilities. | See the table below. Inside the container, pwuser has `CapPrm/CapEff/CapAmb 0` and `CapBnd 0x40000` (SYS_CHROOT only), with `NoNewPrivs 1` and `Seccomp 2`. |
| `init: true` | Each closed browser leaves Chromium helpers reparented to PID 1. The Python server never reaps them, so they accumulate against `pids_limit: 512`. | Three launch-and-close cycles, image and flags unchanged: 6 zombies without init, 0 with `--init`. |
| `RENDERER_MAX_TIMEOUT_SECONDS=120` dropped | It duplicated the code default. `RENDERER_CONCURRENCY` stays, so it can be tuned. | none needed |
| `restart` moved to the prod overlay | The base file sets `restart` on no service. Prod sets `always` on all of them. | `test_renderer.py` covers the prod overlay. |

In-image renderer suite (`harmony-renderer-test:wp1h` with the worktree mounted at `/src`, `--network none`), under the Compose flags `--init --read-only --tmpfs /tmp --tmpfs /home/pwuser --shm-size 1g --security-opt no-new-privileges:true --security-opt seccomp=docker/renderer/seccomp_profile.json --memory 2g --pids-limit 512`:

| Capabilities | Result |
|---|---|
| `--cap-drop ALL` (the proposal) | 13 failed, 97 passed. Every browser test fails at launch with the `sys_chroot` check. |
| Docker's default set | 110 passed |
| `--cap-drop ALL --cap-add SYS_CHROOT` (this branch) | 110 passed |
| `--cap-drop ALL`, with a scratch profile that also allows `chroot` | sandbox and PNG tests pass, which isolates the seccomp gate as the cause. Not adopted, because the profile would no longer be Playwright's verbatim file. |

## Tests

- Red on e79b325: `uv run --no-project --python 3.13 --with pytest pytest tests/infra/test_renderer.py` gave 26 failed. There was no `renderer` service (KeyError), the Dockerfile and profile were missing, and URLBOX/RENDERBOT were set on web and worker.
- Green on d6ef751: `tests/infra` gave 121 passed (renderer, Hasura and browser-share tests).
- WP-0b compose tests: this branch lacks WP-0b, so I trial-merged `mig/integration` (15bdde3) into a throwaway branch. The infra files merged without conflicts; the only conflicts were two other roles' agent-memory files. On the merged tree, `tests/infra` gave 187 passed, including `test_compose.py` (only nginx publishes in base, prod and local; dev publishes on loopback only; third-party images pinned by digest; no default secrets), `test_dockerfiles.py` (it picks up `docker/renderer/Dockerfile`) and `test_renderer.py`. The merge was then aborted and the branch deleted.
- `docker compose config --quiet` passes for base, base+prod, base+dev and build. `docker build --check` reports no warnings. ruff passes, black `-S` passes, and actionlint passes on `renderer.yml`.

## Image and container check

The image was built from the repository root with `docker build -f docker/renderer/Dockerfile -t harmony-renderer:wp1h-infra .`, which pip-installs greenlet 3.5.6, playwright 1.63.0, pyee 13.0.1 and typing-extensions 4.16.0 by hash. It ran through Compose itself: `docker compose -p wp1h-infra-check --env-file <dummy> -f docker-compose.yaml -f <subnet override> up -d --no-deps renderer`. The subnet override was only needed because this host's default address pools are exhausted.

| Check | Result |
|---|---|
| Health | `healthy` (image HEALTHCHECK) |
| Hardening as applied | `user=pwuser readonly=true init=true capdrop=[ALL] capadd=[CAP_SYS_CHROOT] shm=1073741824 mem=2147483648 pids=512 privileged=false ports=map[]`, tmpfs `/tmp` and `/home/pwuser`, security_opt `no-new-privileges:true` plus the profile |
| Networks | only `wp1h-infra-check_render`, `internal=true` |
| Processes | PID 1 `docker-init`, then `python`, both as uid 1001 |
| `/healthz` from a peer on `render` | `200 b'ok'` |
| Off-origin render (`http://169.254.169.254/latest/`) from a peer | `400 {"error": "invalid_request"}`. The log line holds no URL or token. |
| Egress from the renderer | by IP: `Errno 101 Network is unreachable`. By name (`api.urlbox.io`): `Errno -3` name resolution failure. |
| Sandboxed Chromium in the Compose container | `chromium_sandbox=True` launch, then `page.pdf()` gave 5377 bytes starting `%PDF-`. No Chromium process had a `--no-sandbox` or `--no-zygote` flag. |
| Seccomp path | The relative `./docker/renderer/seccomp_profile.json` also loads when Compose runs from `/tmp` with `-f <abs path>`. |

The check container and network were removed with `docker compose down`. The local images `harmony-renderer:wp1h-infra` and `wp1hcheck/harmony-renderer:local` remain.

## Not verified here

- A rootful Docker host. This host runs rootless Docker, which applies no AppArmor profile. On Ubuntu 23.10 and later, with `kernel.apparmor_restrict_unprivileged_userns=1`, Chromium's user-namespace sandbox under `docker-default` should be checked on a deployment-like host before rollout. A failure would fail renders closed, with no `--no-sandbox` fallback, and would not affect other services.
- `.env.example`: settings deny agent reads and edits, including `grep` and `sed`. Removing `URLBOX_API_KEY` and `RENDERBOT_EMAIL` from it is left to the human.
