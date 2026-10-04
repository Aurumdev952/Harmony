---
name: worktree-shell-guard
description: Commands the worktree-isolation guard and hooks refuse, and the forms that work
metadata:
  type: feedback
---

In an isolated worktree, a guard refuses Bash commands it cannot prove stay inside the worktree. That includes `git -C <other path>`, long multi-step chains that mention git, heredocs that contain Python, and docker `--format '{{...}}'`. `python3 ...` is blocked by a hook, so use `uv run python ...`.

**Why:** these refusals cost several round-trips during WP-0d (2026-10-04).

**How to apply:**
- Split chains into plain single commands.
- Write scratch scripts with the Write tool, for example under `/tmp/<wp>-<instance>/`.
- Export trees with `git archive --output=/tmp/x.tar HEAD` as its own command, then untar.
- Run `docker compose -p <unique> ...` with `DOCKER_NAMESPACE`/`DOCKER_TAG` overrides so image tags do not collide with other agents.
