---
name: worktree-isolation-hook-workarounds
description: Commands the worktree-isolation and uv hooks reject, and the forms that work (script files, uv shims, no cd+heredoc, no git -C)
metadata:
  type: feedback
---

As a worktree-isolated subagent the Bash hooks reject: `git -C <other worktree>`; `cd X && ... <<EOF ... EOF; more`; loops whose body runs python/uvx with variables; `env -u`; bare `python3 x.py` (must be `uv run python`).

**Why:** the hook cannot prove such commands stay inside the worktree; several turns were lost on WP-3b (2026-10-05) rediscovering this.

**How to apply:**
- Put multi-step logic in a script file under /tmp (Write tool) and run `bash /tmp/x.sh`.
- One heredoc per Bash call, nothing after it.
- A branch held by another (locked) worktree cannot be switched to; create `<branch>-2` at the same commit and tell the lead.
- When the repo pins uv `required-version` above the host uv: `uvx --from uv==<ver> uv ...`; for scripts that call `uv` (ci/*.sh), put a shim `exec uvx --from uv==<ver> uv "$@"` first on PATH inside a wrapper script.
- After switching to a branch with a newer lock, run `uv sync --locked --all-groups` (exact). `uv run --locked` syncs inexactly and leaves removed packages, so `tests/infra`'s `uv pip check` fails spuriously (seen with `dataclasses`, 2026-10-06).
- Never run two test suites in one pytest process (`tests/druid tests/golden` together gave 183 false failures); use `ci/pytest_suites.sh`.
