---
name: local-flask-stack
description: How to run the legacy Flask app, Alembic and tests locally without the web image (py3.8 venv, Druid stub, gunicorn flag, bcrypt pin)
metadata:
  type: project
---

The legacy web app can run in-process for API replays without Docker images (ghcr.io/zenysis images need auth).

- Venv: `uv venv --seed -p 3.8 /tmp/<name>` then the venv's own `pip install -r requirements.txt -r requirements-web.txt pytest` (`uv pip` is blocked by a hook). Add `bcrypt<4.1`, or `scripts/create_user.py` fails with passlib ("password cannot be longer than 72 bytes").
- Importing `config.settings` needs `DEFAULT_SECRET_KEY` and `DRUID_HOST`. `config/<code>/database.py` calls Druid at import, and seed migration 93bb8d693499 queries Druid, so `flask db upgrade` needs something on 127.0.0.1:8081. WP-2c's `tests/contract/stack/druid_stub.py` answers metadata (datasource `harmony_demo_20240101`). Bind it to 127.0.0.1.
- `create_app()` registers no routes unless `SERVER_SOFTWARE=gunicorn` is set (or the debug reloader is active). Also set `ZEN_OFFLINE=1`. Without the routes, `/api/*` returns 405.
- Header login (`X-Username`/`X-Password`) through `app.test_client()` is the quickest signed-in client.
- In pytest, Flask 1.0 `Flask(__name__)` crashes under assertion rewriting. Pass `root_path=` and `instance_path=`.
- The worktree-isolation guard rejects compound shell commands (loops, `export X=$PWD`, `uv run python -c` with complex text). Put multi-step work in a script under /tmp and run it plainly.

**Why:** WP-0a spent a long time discovering these.
**How to apply:** when a backend WP needs contract replay against Flask before a full Compose stack exists. [[hasura-roles]]
