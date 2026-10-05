---
name: infra-tooling-traps
description: Non-obvious traps when lint/type-checking standalone infra scripts and where infra can place scripts (mypy.ini plugin, repo-root __init__.py, scripts/ ownership, nginx-proxy log format)
metadata:
  type: project
---

- `scripts/**` belongs to the lead, except `scripts/druid`, `scripts/db` and `scripts/perf`. Infra's home for operational scripts is `prod/**`; WP-0g put its script in `prod/browser_share/`. Unit tests go under `tests/infra/`, which is shared since decision 0001.
- The root `[tool.mypy]` in `pyproject.toml` (formerly `mypy.ini`, moved in WP-2f) loads the legacy `sqlmypy` plugin, and the repo root has an `__init__.py`. To strict-check a 3.13 standalone script, add it to `files` in `ci/tools313/pyproject.toml` and run `uv run --project ci/tools313 --locked mypy --config-file ci/tools313/pyproject.toml`. That config is strict and sets `explicit_package_bases`.
- Production nginx is `nginxproxy/nginx-proxy`. Its access log is the `vhost` format (`$host` prefix, `$upstream_addr` suffix) on the container's stdout, not the combined format in a file. From WP-2g on, Compose sets `LOG_FORMAT` (JSON) and `LOG_FORMAT_ESCAPE=json`; the template wraps the value in single quotes, so it must contain none. nginx runs under forego, which puts `nginx.1     | ` in ANSI colours before every line, even in `docker logs` without a TTY. Anything parsing `docker logs <nginx>` must strip that; WP-0g's fixtures lacked it, so the parser read no real line until WP-2g.
- `docker/web/Dockerfile_web` sets `ENV ZEN_PROD 1`, so the web and worker containers run with it (the pipeline image does not). WP-2g first recorded "no image sets ZEN_PROD"; that was wrong and the reviewer caught it. Grep the Dockerfiles before claiming an env var is unset.
- A worktree-isolated agent cannot run git in another agent's worktree, and cannot switch to a branch that a locked worktree has checked out. Ask the lead to detach the old worktree, then `git switch <branch>`; uncommitted files carry over.
- `.gitignore` ignores `*.log`, so a fixture named `access.log` is silently never committed and tests pass only in your worktree. Name log fixtures `*.txt`, and run the final evidence from a clean `git clone` plus `checkout --detach` of the branch tip, with `git status --ignored` showing nothing.
- In a worktree-isolated agent, a Bash command that mixes `git` with loops, `$(git ...)` or long heredocs is refused. Run git commands on their own.

**Why:** each of these cost a retry during WP-0g (2026-10-04).
**How to apply:** follow these before the first lint, type check or commit in an infra WP. The mypy item was updated for WP-2f's layout.
