---
name: worktree-guard-bash
description: The worktree-isolation guard rejects Bash it cannot parse; how to phrase commands so they run
metadata:
  type: feedback
---

In an isolated worktree, the guard refuses Bash commands it cannot verify: `uv run ... --delimiter ';'` (a quoted `;` argument), heredocs that create files outside the worktree, compound `cd /tmp && ...` chains, and `git` with `A..B` plus pipes in loops.

**Why:** it must prove that no git command escapes the worktree, so any construct it cannot parse is refused.

**How to apply:**
- Create files with the Write tool.
- Put step arguments into a Python harness or case table instead of the shell line.
- Run one plain git command per call.
- `uv run --no-project python - <<'EOF'` from the worktree root is accepted.
- `python3 x.py` is blocked; use `uv run python x.py`.
