---
name: tooling-traps
description: Command traps in Harmony agent worktrees - ownership.py invocation, compound bash refused, onupdate as a test probe, task_gate reads the local branch ref, ZenysisLogger propagation doubles caplog
metadata:
  type: feedback
---

- Run `uv run python scripts/agents/ownership.py who <path>`. A hook rejects plain `python3`.
- In a worktree-isolated subagent, a compound Bash command that writes files (a heredoc append plus `sed -i` chained with `&&`) is refused as "too complex to verify". Make edits with the Edit tool, and keep each Bash call to plain commands. A `git commit -F - <<EOF` heredoc on its own is allowed.
- `UTCTimestampMixin.last_modified` has `onupdate=utcnow()`, so a bulk `Query.update` bumps it on every row it matches. Use this to test that a WHERE clause excludes rows whose values would not otherwise change, for example the revoked-token filter in `update_user_api_tokens`.

- `task_gate.py WP-<id>` diffs the **local** branch ref named in the WP front matter, not your HEAD. When that branch is checked out in a dead agent's worktree, you work detached and push `HEAD:refs/heads/<branch>`; the gate then still judges the old commit. Check the merged head yourself: `git diff --name-only mig/integration...HEAD` against the `files:` claims, and `ownership.py check --role ... --head HEAD`.
- Since WP-2g's `log/config.py`, `ZenysisLogger` propagates to root. A test that adds `caplog.handler` to that logger sees every record twice; put a handler of your own on the logger instead (WP-0h `refusals` fixture, 2026-10-06).

**Why:** these cost retries on WP-2c's F12 lint fix (2026-10-05) and the WP-0h merge with WP-2c (2026-10-06).
**How to apply:** any supporting-role fix in a `.claude/worktrees/agent-*` checkout.
