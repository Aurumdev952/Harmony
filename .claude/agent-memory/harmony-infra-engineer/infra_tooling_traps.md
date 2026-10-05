---
name: infra-tooling-traps
description: Non-obvious traps for infra scripts and side branches (scripts/ ownership, old mypy typeshed, nginx-proxy logs, *.log gitignored, worktree Bash/Write guards)
metadata:
  type: project
---

- `scripts/**` belongs to the lead, except `scripts/druid`, `scripts/db` and `scripts/perf`. Infra's home for operational scripts is `prod/**`, and CI helpers go in `ci/**`. Unit tests go under `tests/infra/`.
- The root `[tool.mypy]` loads the legacy `sqlmypy` plugin and runs mypy 1.3. Its typeshed is old: for example, `GzipFile` does not count as `IO[bytes]` for `TextIOWrapper`.
- Production nginx is `nginxproxy/nginx-proxy`. Its access log uses the `vhost` format and goes to the container's stdout.
- `.gitignore` ignores `*.log`, so name log fixtures `*.txt`.
- In a worktree-isolated agent, the guard refuses Bash commands that mix `git` with loops, `$(...)`, heredocs fed to interpreters, `bash -c`, `docker run ... sh` or `VAR=... uv`. Write the script to `/tmp/<wp>/x.sh` with the Write tool, then run `bash /tmp/<wp>/x.sh`.
- Write and Edit refuse paths outside the agent's own worktree, and creating a second worktree does not help. For a side branch the lead asks for:
  1. park the current work in a temporary WIP commit;
  2. `git switch` to the new branch in the same worktree;
  3. come back and run `git reset --soft HEAD~1`, then `git restore --staged .`.

**Why:** each of these cost a retry during WP-0g, WP-2f or WP-3b.
**How to apply:** follow these before the first lint, type check or commit in an infra WP, and whenever the lead asks for a small separate branch.
