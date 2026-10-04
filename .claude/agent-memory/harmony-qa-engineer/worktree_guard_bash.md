---
name: worktree-guard-bash
description: The worktree-isolation guard rejects Bash it cannot parse; how to phrase commands so they run
metadata:
  type: feedback
---

In an isolated worktree, the guard refuses Bash commands it cannot verify:
- `uv run ... --delimiter ';'` (a quoted `;` argument);
- heredocs that create files outside the worktree;
- compound `cd /tmp && ...` chains;
- a variable used as the command name (`C=/x; $C/run.sh`);
- `uv run python - <<EOF` fed scripts containing f-string braces, when chained with other commands;
- `git` with `A..B` plus pipes in loops.

A refused command runs nothing. Any follow-up command that depends on it then runs against missing files and can look green. Always check that the setup step actually ran.

**Why:** the guard must prove that no git command escapes the worktree, so it refuses any construct it cannot parse.

**How to apply:**
- Write edit scripts to `/tmp/*.py` with the Write tool, then run `uv run --no-project python /tmp/x.py` on its own.
- Use literal absolute paths, not variables, for commands.
- For a clean checkout, use `git archive --format=tar -o /tmp/x.tar <sha>` alone, then extract it in a separate call.
- Run one plain git command per call.
- `python3 x.py` is blocked; use `uv run python x.py`.
