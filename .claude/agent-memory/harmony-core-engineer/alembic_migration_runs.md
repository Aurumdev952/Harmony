---
name: alembic-migration-runs
description: How to exercise web/server/migrations/env.py and run `flask db upgrade` from scratch cheaply, and the traps found doing it (WP-2g, 2026-10-04)
metadata:
  type: reference
---

- **3.8 web env.** `uv venv --seed --python 3.8 venv38`, then `venv38/bin/pip install -r requirements.txt -r requirements-web.txt "pytest<8.4" freezegun` as one plain command with absolute paths (about 5 minutes). Name it `venv*` so `.gitignore` covers it. `.venv38` is not ignored.
- **`flask db current` is broken** on the pinned Flask-Migrate 2.5.2 with the alembic 1.14 that `alembic>=1.7.1` resolves to (`current() got an unexpected keyword argument 'head_only'`). To run env.py cheaply, use `flask db stamp head` against `DATABASE_URL=sqlite:///<tmp file>` with `FLASK_APP=web.server.app ZEN_OFFLINE=1`. No Postgres is needed.
- **A full `flask db upgrade` from empty needs a Druid coordinator.** Seed 93bb8d693499 calls `:8081/druid/coordinator/v1/metadata/datasources`, and the port is hard-coded in `BaseDruidConfig.build_endpoint`. A stub container that answers `[]` makes the seed take its no-datasource branch. Docker bridge IPs are not reachable from the host here, so publish the stub on a spare loopback address (`-p 127.0.82.1:8081:8081`, `DRUID_HOST=http://127.0.82.1`). The working script is `docs/modernisation/work/WP-2g-evidence/core_flask_db_upgrade.sh`. The upgrade reaches head `2b730c14f514` in about a minute.
- **SQLAlchemy sets the `sqlalchemy` logger to WARN at import** when it is NOTSET (1.3 `sqlalchemy/log.py`, also in 1.4 and 2.x). Setting `sqlalchemy.engine` to WARNING yourself is redundant, and a test cannot tell the difference.
- **`web.server.app_base` imports models before anything imports `log`.** So with `FLASK_APP=web.server.app_base`, the first SQLAlchemy warning prints as plain text. `web.server.app` does not have this problem.

Related: [[running-legacy-python-tests]], [[worktree-shell-guard]]
