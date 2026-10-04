---
name: review-tooling-traps
description: Commands that work (and fail) when reviewing a WP branch from an isolated reviewer worktree: worktree guard, python3 hook, stale SPEC ownership, zsh quirks, cross-branch overlays
metadata:
  type: feedback
---

Run review commands as plain, one-git-per-command calls from your own worktree; inspect other branches through a detached scratch worktree or `git archive`.

**Why:** In the WP-2f review (2026-10-04) the worktree-isolation guard refused every compound command naming git: loops over branches, `$(git ...)`, `git archive ... | tar`, and even tar or uv with runtime-computed arguments. A PreToolUse hook also rejects `python3 scripts/agents/...` and asks for `uv run python ...`.

**How to apply:**
- `git worktree add --detach /tmp/<name> <branch>` from your own worktree is allowed. Remove it afterwards with `git worktree remove --force` and `git worktree prune`.
- To read another branch's files, run `git archive -o /tmp/x.tar <branch> [paths]` as one command, then `tar -x -f /tmp/x.tar -T list.txt` as a second.
- Python one-liners passed with `-c` get blocked. Write the snippet to /tmp and run `uv run --no-project --python 3.13 python /tmp/snippet.py`.
- Your worktree can sit on an old commit whose SPEC has a stale ownership table. In WP-2f, `tests/**` showed as qa there but is shared on integration. Run `ownership.py check --role <r> --head <branch> --base mig/integration` from a checkout of the branch under review.
- zsh treats `echo ====` as equals-expansion and errors. Use `'---'` separators.
- To test cross-WP interactions, overlay other in-flight suites (`tests/golden`, `tests/contract`, `tests/pipeline`) into the scratch worktree and run the CI command. In WP-2f this showed that WP-2c and WP-2d need `hypothesis`.
- `mig/integration` moves during a review. Use `--merge-base` when you diff for "files this branch changed".
