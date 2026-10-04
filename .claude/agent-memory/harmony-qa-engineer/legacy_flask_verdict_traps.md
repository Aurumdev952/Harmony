---
name: legacy-flask-verdict-traps
description: Traps when re-running tests/web or probes across scratch worktrees (cwd shadows PYTHONPATH, worktree guard, uv rules) and the cross-tree oracle pattern that worked for WP-0c
metadata:
  type: feedback
---

When you run pytest against a scratch worktree under /tmp, run it from that tree (`cd /tmp/<tree> && PYTHONPATH=/tmp/<tree> uv run ... python -m pytest ...`).
**Why:** `python -m pytest` puts the cwd first on sys.path. From the agent worktree, the agent's own `web/` silently shadows the tree under test. For WP-0c the branch probes "failed" until I fixed this.
**How to apply:**
- Keep each Bash call to a single command. The worktree guard refuses heredocs combined with commands and refuses `cd` chains. Write scripts with the Write tool, then run them alone.
- `python3` is blocked, so use `uv run --no-project python`.
- Build the requirements with the sed recipe in WP-0c.md into your own /tmp file. Do not reuse another agent's /tmp/reqs.txt, which has diverged.
- For a venv without flask_jwt_extended, use `requirements.txt` alone on `-p 3.8`. On 3.9, psycopg2 builds from source and fails.

Patterns that gave strong evidence:
- Drive routes through a Flask test client with a LoginManager request_loader, a real flask_principal Identity and the real `authentication_required` decorator, not `__wrapped__`.
- Dump observations to JSON from both trees and diff them. This works for parity checks (INV-2).
- Run a seeded random filter generator through `AuthorizedQueryClient.run_query` in both trees and `cmp` the outputs.
- Mutation-check every probe: apply a named mutant to a third worktree and confirm the tests fail.
- The SEC-4 AST guard does not catch `getattr(current_app, 'system_' + ...)`. That is a known limit of static scanning.
