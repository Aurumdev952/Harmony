---
name: reference-contract-stack
description: Traps when running the WP-2c contract stack (tests/contract/stack) for replay or review
metadata:
  type: reference
---

Current as of the WP-2c rework (2026-10-05):

- Always start it through `tests/contract/stack/stack.sh up`; `compose.yaml` alone no longer works (it needs `CONTRACT_WEB_IMAGE` and six generated secrets). WP-2b's `tests/authz/stack.sh` drove `compose.yaml` directly and must switch to `stack.sh` with its own `CONTRACT_PROJECT`/`CONTRACT_WEB_PORT`/`CONTRACT_USERNAME`.
- The web image is rebuilt on every `up` (layer cache) and tagged `harmony-contract-web-server:<hash of requirements*.txt and docker/web/Dockerfile_web-server>` (no shim image since WP-0b pinned bcrypt, 2026-10-04), so requirement changes are never masked by a stale image.
- Secrets live in `$XDG_RUNTIME_DIR/<project>.env` (else `~/.local/state/harmony-contract/`), mode 600, one `NAME=<64 hex>` line each; `CONTRACT_PASSWORD` is the admin password. `down` deletes it.
- Overlays switch on Redis `requirepass` and the Hasura admin secret when the checked-out code reads `REDIS_PASSWORD` (WP-0b) / `HASURA_ADMIN_SECRET` (WP-0a).
- Everything is on an `internal: true` network: no egress (Mailgun, Urlbox fail fast). Only `forward` publishes `127.0.0.1:$CONTRACT_WEB_PORT`.
- Set `CONTRACT_PROJECT` and `CONTRACT_WEB_PORT` per instance; two `up`s with defaults share one compose project.
- Docker Hub may 429 on `python:3.8` metadata; `Dockerfile_web-server` pins it by digest (WP-0b), so a local copy of that digest satisfies the build.
- Full replay takes about 20 s; recording about the same. Recordings reproduce byte for byte on fresh and used stacks, so `diff -r` against a copy is a valid determinism check.
- The offline mock Druid client (`util/offline_mode.py`) is unseeded random; only shapes are stable. See [[contract-stack-traps]].
- Other agents' stacks (e.g. WP-1h e2e) pick loopback ports in the same 58xxx range; check `docker ps` for the port before `up`, or `up` fails at the forwarder after building everything.
- A Relay recording whose every `edges` is empty must be annotated `recorded (empty connection, <reason>)` in INVENTORY.md, and the annotation must go once items appear; `test_catalogue` enforces both directions.
- 2026-10-05: the rootless Docker bridge can lose egress (container DNS and literal-IP connects time out while the host is fine). `stack.sh up` then fails at the image's `pip install` (clone of potion), because a default-network build misses the layer cache that a `--network host` build created. Run an untracked copy of `stack.sh` beside it with only `--network host` added to `docker build` (same tag), delete it after, and record the deviation in the WP log. Never restart or prune the shared daemon.
