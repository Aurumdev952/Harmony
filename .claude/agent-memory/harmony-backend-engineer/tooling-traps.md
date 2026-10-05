---
name: tooling-traps
description: Command traps in Harmony agent worktrees - ownership.py invocation, compound bash refused, onupdate as a test probe
metadata:
  type: feedback
---

- Run `uv run python scripts/agents/ownership.py who <path>`. A hook rejects plain `python3`.
- In a worktree-isolated subagent, a compound Bash command that writes files (a heredoc append plus `sed -i` chained with `&&`) is refused as "too complex to verify". Make edits with the Edit tool, and keep each Bash call to plain commands. A `git commit -F - <<EOF` heredoc on its own is allowed.
- `UTCTimestampMixin.last_modified` has `onupdate=utcnow()`, so a bulk `Query.update` bumps it on every row it matches. Use this to test that a WHERE clause excludes rows whose values would not otherwise change, for example the revoked-token filter in `update_user_api_tokens`.

**Why:** these cost retries on WP-2c's F12 lint fix (2026-10-05).
**How to apply:** any supporting-role fix in a `.claude/worktrees/agent-*` checkout.
