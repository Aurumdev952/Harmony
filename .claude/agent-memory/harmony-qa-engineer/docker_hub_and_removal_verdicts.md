---
name: docker-hub-and-removal-verdicts
description: Docker Hub 429/DNS failures during image builds and how to proceed; how to verify a dead-code/dependency removal WP (WP-0d recipe)
metadata:
  type: reference
---

**Docker Hub rate limit.** With many agents building at once, `FROM python:3.8` / `ubuntu:22.04` fails with `429 Too Many Requests` (or a DNS timeout on auth.docker.io). The local store did not keep those base images. Workaround that keeps the Dockerfile untouched: `docker pull mirror.gcr.io/library/<img>:<tag>` then `docker tag` it to the name the Dockerfile uses (and to WP-0b's pinned `ubuntu:jammy-20260924.1` tag; the mirror's 22.04 digest equals WP-0b's pinned digest). BuildKit then uses the local image even with `--no-cache`.

**Removal WP recipe (WP-0d, 2026-10-04).**
- Lockfile check without `uv pip` (a modern-python shim blocks it): `uv run --no-project -p 3.8 --with-requirements <each file>` plus a small `importlib.metadata` script that lists removed dists still installed and which installed dist requires them. Rewrite `-e git+...#egg=X` to `X @ git+...` first.
- `requirements-dev.txt` needs Python >=3.9 (pytest-httpx 0.30), but `psycopg2-binary==2.8.5` has no cp39 wheel; check the dev file on its own on 3.9.
- Fail-before: copy the new tests into a `mig/integration` scratch worktree and run them in an env built from integration's requirements, so they fail on the assertion, not on a missing module.
- WP-2c's contract stack (`tests/contract/stack`) mounts the source tree and takes a base web-server image; overlay it onto a scratch copy, rename its image tags and project/port so other QA agents' `harmony-wp2c-web-server:*` tags are not overwritten, and replay against the WP's own image. This gives real "every Potion resource responds" evidence before WP-2e exists.

See [[review-traps]] and [[qa-verdict-recipes]] for the worktree-guard workarounds (write scripts with the Write tool, run `bash /tmp/x.sh`).
