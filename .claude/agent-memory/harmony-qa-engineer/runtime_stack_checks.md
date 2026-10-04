---
name: runtime-stack-checks
description: How QA runs the real web and worker containers for infra and secret WPs (WP-0b recipe), plus traps such as Celery swallowing startup errors and Docker Hub 429s
metadata:
  type: reference
---

**Stack recipe (WP-0b, 2026-10-04).** Use the branch's `docker-compose.yaml` and `docker-compose.dev.yaml`, plus a /tmp overlay that does these things:
- moves ports to 127.0.0.1 high ports (25000, 25432, 26379) with `ports: !override`;
- uses `tmpfs` for postgres and redis data;
- adds a `druid-stub` service (copy `tests/contract/stack/druid_stub.py` from the WP-2c worktree);
- runs `web`, `worker` and a one-shot `web-init` (flask db upgrade, then `scripts/create_user.py`) from a branch-built `Dockerfile_web-server` image, with the branch mounted read-only at `/zenysis`, `ZEN_OFFLINE=1` and `DRUID_HOST=http://druid-stub`.
Before `web-init`, create the database `harmony_demo-local` with psql. Web serves `/login` about 60 s after start.

**Docker context is rootless.** Wrapping compose in `env -i` drops the context. Pass `DOCKER_HOST=unix:///run/user/1000/docker.sock`. The Bash guard also refuses commands that set `HOME`, so put the `env -i` inside a /tmp script.

**Celery swallows `worker_process_init` errors.** If startup code raises in a pool child, the worker logs `Signal handler ... raised`, then reports `ready`, and the `celery status` healthcheck says OK. So "the worker refuses to start" must be checked by running the container and reading its state, not inferred from the code.
**Why:** WP-0b claimed web, worker and pipeline all refuse `changeme`. The web container exited 1, but the worker stayed up and healthy.
**How to apply:** for any startup-validation WP, run each service with the bad value and check `docker ps` status and exit codes.

**Docker Hub returns 429 after about 10 `imagetools inspect` calls.** Verify digests early, once per unique ref, with sleeps between calls. A container that runs from `image@sha256:` also proves the digest exists.

**Cached builds prove nothing about checksums.** Rebuild downloader stages with `--no-cache --progress=plain` and look for the `: OK` lines.

**Fail-before for a handler fix.** A test can fail on the merge base for an unrelated reason. WP-0b's old-cookie test failed there with `KeyError 'sqlalchemy'`. Revert only the fixed file on the branch and rerun to see the intended failure.
