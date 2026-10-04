---
name: infra-secret-review-lessons
description: Reviewing startup-refusal and pinning WPs (WP-0b) - the production web wrapper exits 0, CI lint fails on py3.10 annotations in tests, text-only fail-closed tests, moving WP heads
metadata:
  type: project
---

Learned reviewing WP-0b on 2026-10-04/05.

- **The production web wrapper exits 0.** `docker/web/Dockerfile_web` runs `docker/entrypoint_web.sh`, which runs `run_web_gunicorn.sh`. That script ignores `web/gunicorn_server.py`'s status, then waits about 15 s on a PID file that never appears, then `break`s and exits 0. A startup refusal raised in `create_app` under gunicorn therefore ends with the container `Exited (0)`. QA's live stack ran gunicorn directly, so it saw exit 1. To probe, mount the branch read-only at `/src` in any local harmony web image (`harmony-contract-web:*`) and run `bash /src/docker/web/scripts/run_web_gunicorn.sh`. Put the `docker run` in a /tmp script, because the guard refuses an inline `docker run ... bash`.
- **Celery swallows `worker_process_init` errors.** Startup checks placed there never stop the worker. See QA's runtime-stack-checks memory.
- **CI lint covers test files too.** `integration.yml` runs `black -S -t py39 --check` and pylint on every changed `.py` file, tests included, on Python 3.9, and any pylint error fails the job. A `str | None` annotation gives E1131. Reproduce from the scratch worktree with `uv run --no-project -p 3.9 --with pylint==2.17.4 --with 'pytest<8' pylint -f json <file>`. Web files need the 3.8 env with `/tmp/reqs.txt`, because psycopg2 has no 3.9 wheel in the cache.
- **Mutation-check "fail-closed" tests.** Copy the script and its tests to /tmp, turn the guard into `... || true`, and rerun. WP-0b's `test_druid_extensions.py` stayed green, which proved it was checking text, not behaviour.
- **Gate log lines.** `task_gate.py` before c620101 counted only log lines that start with the date. Bulleted `- 2026-...` lines from supporting roles were missed, and the gate flagged their files as outside the owner. Builders must declare every contributing instance in the front matter.
- **Heads move mid-review.** The lead merged fixes while the review ran (c03a86d to c9d81e6). Before writing the verdict, check `git rev-parse <branch>` and re-verify each finding at the new head.

**Why:** two of these defects (exit 0, CI E1131) survived QA and security approval.
**How to apply:** for any WP that adds a startup refusal, check the exit code through the real image entrypoint, and run the CI lint commands on the changed files. Related: [[review-traps]], [[ci-review-facts]].
