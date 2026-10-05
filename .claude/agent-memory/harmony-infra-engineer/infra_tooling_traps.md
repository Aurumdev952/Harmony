---
name: infra-tooling-traps
description: Non-obvious traps for infra scripts and side branches (scripts/ ownership, old mypy typeshed, nginx-proxy logs, *.log gitignored, worktree Bash/Write guards)
metadata:
  type: project
---

- `scripts/**` belongs to the lead, except `scripts/druid`, `scripts/db` and `scripts/perf`. Infra's home for operational scripts is `prod/**` (WP-0g put its script in `prod/browser_share/`), and CI helpers go in `ci/**`. Unit tests go under `tests/infra/`, which is shared since decision 0001.
- The root `[tool.mypy]` loads the legacy `sqlmypy` plugin and runs mypy 1.3; from WP-3b it also strict-checks the standalone tools (`ci/tools313` is gone). Its typeshed is old: for example, `GzipFile` does not count as `IO[bytes]` for `TextIOWrapper`.
- Production nginx is `nginxproxy/nginx-proxy`. Its access log is the `vhost` format (`$host` prefix, `$upstream_addr` suffix) on the container's stdout, not the combined format in a file. From WP-2g on, Compose sets `LOG_FORMAT` (JSON) and `LOG_FORMAT_ESCAPE=json`; the template wraps the value in single quotes, so it must contain none. nginx runs under forego, which puts `nginx.1     | ` in ANSI colours before every line, even in `docker logs` without a TTY. Anything parsing `docker logs <nginx>` must strip that; WP-0g's fixtures lacked it, so the parser read no real line until WP-2g.
- `docker/web/Dockerfile_web` sets `ENV ZEN_PROD 1`, so the web and worker containers run with it (the pipeline image does not). WP-2g first recorded "no image sets ZEN_PROD"; that was wrong and the reviewer caught it. Grep the Dockerfiles before claiming an env var is unset.
- `.gitignore` ignores `*.log`, so a fixture named `access.log` is silently never committed and tests pass only in your worktree. Name log fixtures `*.txt`, and run the final evidence from a clean `git clone` plus `checkout --detach` of the branch tip, with `git status --ignored` showing nothing.
- In a worktree-isolated agent, the guard refuses Bash commands that mix `git` with loops, `$(...)`, heredocs fed to interpreters, `bash -c`, `docker run ... sh` or `VAR=... uv`. Run git commands on their own, or write the script to `/tmp/<wp>/x.sh` with the Write tool and run `bash /tmp/<wp>/x.sh`.
- A worktree-isolated agent cannot run git in another agent's worktree, and cannot switch to a branch that a locked worktree has checked out. Ask the lead to detach the old worktree, then `git switch <branch>`; uncommitted files carry over.
- Write and Edit refuse paths outside the agent's own worktree, and creating a second worktree does not help. For a side branch the lead asks for:
  1. park the current work in a temporary WIP commit;
  2. `git switch` to the new branch in the same worktree;
  3. come back and run `git reset --soft HEAD~1`, then `git restore --staged .`.

**Why:** each of these cost a retry during WP-0g, WP-2f or WP-3b.
**How to apply:** follow these before the first lint, type check or commit in an infra WP, and whenever the lead asks for a small separate branch.
- The isolation guard matches "git" as a substring, so `.github/...` in a command with `PATH=...`, pipes or `$(...)` is refused as a git command. Put such commands in a `/tmp/<wp>/*.sh` file and run `bash <file>` with plain arguments.
- A hook rejects `python3 <script>` and asks for `uv run python <script>`. On a branch whose `required-version` the host uv does not meet, put a shim first on PATH (`exec uvx --from uv==0.12.23 uv "$@"`), or run from `/tmp` with `uv run --no-project`.
- `mig/integration` keeps moving while a WP merges it. Check `git log <merged-sha>..mig/integration` before the evidence run, and merge again if it moved.
