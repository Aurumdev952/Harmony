---
name: infra-tooling-traps
description: Non-obvious traps when lint/type-checking standalone infra scripts and where infra can place scripts (mypy.ini plugin, repo-root __init__.py, scripts/ ownership, nginx-proxy log format)
metadata:
  type: project
---

- `scripts/**` belongs to the lead, except `scripts/druid`, `scripts/db` and `scripts/perf`. Infra's home for operational scripts is `prod/**`; WP-0g put its script in `prod/browser_share/`. Unit tests go under `tests/infra/`, which is shared since decision 0001.
- The repo `mypy.ini` loads the legacy `sqlmypy` plugin, and the repo root has an `__init__.py`. To strict-check a standalone script, run `uvx --python 3.13 mypy --config-file=/dev/null --strict --explicit-package-bases <files>`, with `MYPYPATH` set to the script dir when tests import it.
- Production nginx is `nginxproxy/nginx-proxy`. Its access log is the `vhost` format (`$host` prefix, `$upstream_addr` suffix) on the container's stdout, not the combined format in a file.
- In a worktree-isolated agent, a Bash command that mixes `git` with loops, `$(git ...)` or long heredocs is refused. Run git commands on their own.

**Why:** each of these cost a retry during WP-0g (2026-10-04).
**How to apply:** follow these before the first lint, type check or commit in an infra WP. Re-check the mypy item after WP-2f replaces `mypy.ini`.
