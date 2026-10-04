---
name: authz-suite-harness
description: How the tests/authz suite runs (root uv project, Python 3.9 legacy web stack, WP-2c live stack) and the traps hit building it in WP-2b
metadata:
  type: project
---

`tests/authz/run.sh` is the only supported way to run the authz suite. It is `uv run --with pyyaml --with hypothesis pytest tests/authz` on the root uv project (`pyproject.toml`, from WP-2a), which pins the legacy web stack (Flask 1.0.1, the Flask-Potion fork) on Python 3.9. Python 3.13 does not work yet.

**Why:** WP-2a added the root uv project; before it merged, this suite used `uv run --no-project -p 3.8 --with-requirements` with the `-e git+` lines rewritten. PyYAML and Hypothesis are added per run until WP-2f folds them into the dev group.

**How to apply:**
- Select tests with `-k`, not paths. run.sh already passes `tests/authz`, and a second path makes pytest collect the same tests twice.
- The live-stack layer (`-m authz_http`) runs against `tests/authz/stack.sh up`, a thin wrapper around `tests/contract/stack/stack.sh` (WP-2c) under project `harmony-wp2b-authz` on port 58660. It refuses a non-loopback `AUTHZ_BASE_URL` and deletes every user and group it creates on teardown.
- Avoid running plain `python` from the repo root with the project on PYTHONPATH: `tests/authz/http/` shadows stdlib `http` for urllib3. run.sh is fine; one-off probes should run from /tmp with `--no-project`.

Traps found while building it:
- The worktree-isolation Bash checker refuses heredocs, `$VAR` arguments and `cd` into subdirectories. Write files with the Write tool and keep commands plain.
- Page routes deny with HTTP 200 and the unauthorized page. Classify responses by their last `*.bundle.js`.
- Users are created through the admin API like this: `POST /api2/user` (needs `phoneNumber`), then `POST /api2/user/<id>/password`, then a full-object `PATCH /api2/user/<id>` with role URIs. `POST /api2/user/<id>/roles` returns 500. `username` is varchar(50).
- Pooled keep-alive connections get dropped now and then. Sessions use a urllib3 Retry for idempotent methods.

Related: [[authz-escalations-found]]
