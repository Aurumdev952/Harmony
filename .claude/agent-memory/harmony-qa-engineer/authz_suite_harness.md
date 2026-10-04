---
name: authz-suite-harness
description: How the tests/authz suite runs (uv on Python 3.8, private WP-2c stack copy) and the traps hit while building it in WP-2b
metadata:
  type: project
---

`tests/authz/run.sh` is the only supported way to run the authz suite. It rewrites `-e git+` lines in requirements*.txt and runs `uv run --no-project -p 3.8 ...`. The web stack pins Python 3.8, Flask 1.0.1 and the Flask-Potion fork, so Python 3.13 does not work yet.

**Why:** There is no pyproject.toml, and uv rejects editable requirement lines.

**How to apply:**
- Select tests with `-k`, not paths. run.sh already passes `tests/authz`, and a second path makes pytest collect the same tests twice.
- The live-stack layer (`-m authz_http`) runs against `tests/authz/stack.sh up`. That script drives WP-2c's `tests/contract/stack/compose.yaml` under project `harmony-wp2b-authz` on port 58660, with `--no-build`, so the shared `harmony-wp2c-web-server:local` image is never rebuilt.

Traps found while building it:
- The worktree-isolation Bash checker refuses heredocs, `$VAR` arguments and `cd` into subdirectories. Write files with the Write tool and keep commands plain.
- Page routes deny with HTTP 200 and the unauthorized page. Classify responses by their last `*.bundle.js`.
- Users are created through the admin API like this: `POST /api2/user` (needs `phoneNumber`), then `POST /api2/user/<id>/password`, then a full-object `PATCH /api2/user/<id>` with role URIs. `POST /api2/user/<id>/roles` returns 500. `username` is varchar(50).
- Pooled keep-alive connections get dropped now and then. Sessions use a urllib3 Retry for idempotent methods.

Related: [[authz-escalations-found]]
