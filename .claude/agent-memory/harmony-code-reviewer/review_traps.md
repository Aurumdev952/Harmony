---
name: review-traps
description: Traps when reviewing Harmony WP branches - ignored fixtures, worktree-isolation git limits, ownership.py invocation and base, zsh quirks
metadata:
  type: project
---

- Always re-run a WP's tests in a clean detached scratch worktree (`git worktree add --detach /tmp/rev-<wp> <branch>`, then `git worktree remove --force`). Builder evidence comes from their own worktree, which can hold ignored files. `.gitignore:158` has `*.log`, so a fixture such as `tests/infra/testdata/zz/access.log` was never committed in WP-0g. On a clean checkout 6 tests failed, while the WP claimed 49 passed. `git check-ignore -v <path>` shows the ignore rule.
- `.gitignore` matches no ownership row, so it belongs to the lead. A builder fixes an ignored fixture by renaming it or with `git add -f`.
- Worktree-isolated agents: the guard refuses git inside loops, `$(...)`, `git -C <other worktree>` and heredocs. To find files across branches, use `git log --all --name-status -- <path>`. Write /tmp probe scripts with the Write tool. You can still `ls`/`cat` another agent's worktree.
- `ownership.py` refuses `python3`. Run `uv run --no-project python scripts/agents/ownership.py check --role <r> --head HEAD` from the scratch worktree. Lead merges (decision branches) show up as lead-owned files. `git diff --stat mig/integration...<branch>` gives the WP's own diff.
- zsh: `echo ====` errors out (EQUALS expansion). Use another separator.

**Why:** each of these cost a retry or almost hid a blocker during the WP-0g review (2026-10-04).
**How to apply:** set up the scratch worktree and the clean test run before reading the diff in detail. See also [[review-gate-arithmetic]].
