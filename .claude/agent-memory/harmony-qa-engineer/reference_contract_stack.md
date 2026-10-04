---
name: reference-contract-stack
description: Traps when running the WP-2c contract stack (tests/contract/stack) for replay or review
metadata:
  type: reference
---

Learned reviewing WP-2c on 2026-10-04:

- `stack.sh up` builds `harmony-wp2c-web-server:base` only if the tag is missing. The tag is global
  (shared by every worktree and by the WP-2b authz stack, which reuses this compose file with
  `CONTRACT_PROJECT=harmony-wp2b-authz`, port 58660). A cached base keeps old Python deps, so a WP that
  changes requirements (0b bcrypt pin, 2f, 3d) must `docker rmi` it or replay runs on stale deps.
- Project name and port are fixed defaults (`harmony-wp2c-contract`, 58650). Two agents running `up`
  with defaults share one compose project and clobber each other: set `CONTRACT_PROJECT` and
  `CONTRACT_WEB_PORT` per instance.
- Docker Hub returns 429 on metadata HEAD for `python:3.8` under load; `docker build --pull=false`
  uses the local copy.
- The credentials file is `$XDG_RUNTIME_DIR/<project>.env` (mode 600), removed by `down`. `stack.sh env`
  prints no password; replay reads it via `CONTRACT_CREDENTIALS_FILE`.
- Full replay takes about 20 s; recording about 18 s. Recordings reproduce byte for byte on fresh and
  used stacks, so `diff -r` against a copy is a valid determinism check.
- The offline mock Druid client (`util/offline_mode.py`) is unseeded random; only shapes are stable.
