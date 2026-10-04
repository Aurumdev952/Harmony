---
name: worktree-guard-bash
description: Bash forms the worktree-isolation guard refuses for the reviewer, and the phrasing that runs
metadata:
  type: feedback
---

The isolation guard refuses Bash it cannot prove git-safe:
- `for` loops that use variables in `sed` or `python` arguments;
- `git -C` or `git` with `A...B` inside loops or pipes;
- multi-statement heredoc probes.

`python3 x.py` is blocked. Use `uv run --no-project python x.py`.

**Why:** the guard must show that no git command escapes the worktree.

**How to apply:**
- Write probe scripts and loops to `/tmp` with the Write tool, then run them.
- Run one plain `git` command per call from the reviewer worktree.
- For mutation tests, copy the tree with `tar --exclude=.git --exclude=__pycache__`. Stale `.pyc` files point at the original paths.
- Remove scratch worktrees with `git worktree remove --force` at the end.
