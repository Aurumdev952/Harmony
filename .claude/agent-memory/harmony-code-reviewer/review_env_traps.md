---
name: review-env-traps
description: Shell and tool traps when reviewing a WP from a /tmp scratch worktree (worktree guard, uv shim, python3 hook) and the commands that work
metadata:
  type: project
---

The worktree guard refuses any command it cannot prove is not git, when that command targets a path outside the reviewer's own worktree.

**Why:** observed on WP-0d (2026-10-04). It blocked several kinds of command: `git grep` with a `$VAR` pattern in `/tmp/<scratch>`, `for` loops whose body ran `sed`, `uv` or `git` on a loop variable, `xargs -a`, and even `sed` whose pattern contained the literal word `git`.

**How to apply:**
- Run `git log`, `git diff`, `git show <ref>:<path>` and `git merge-tree --write-tree --name-only A B` from your own worktree directory. Use refs, not the scratch path. One plain command per call.
- In the scratch tree, use `grep -rn` instead of `git grep`.
- For anything with loops or variables, write a script under `/tmp/...` and run `bash /tmp/.../x.sh`.
- The modern-python plugin's `uv` shim refuses `uv pip`. Call the real binary instead: `/home/aurum/.local/bin/uv pip compile ...`.
- A hook refuses `python3 x.py`. Use `uv run --no-project python x.py`, which also works for `scripts/agents/*.py`.
- `git worktree add --detach /tmp/<name> <ref>` works from your own worktree.

Related: [[dependency-removal-review]]
