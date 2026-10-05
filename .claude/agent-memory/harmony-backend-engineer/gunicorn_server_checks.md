---
name: gunicorn-server-checks
description: How to test and type-check web/gunicorn_server.py (gevent patch at import, mypy --strict on a 3.8 target, ruff with no repo config) and run it live without the real app
metadata:
  type: reference
---

Found during the WP-2g request on 2026-10-04.

- **Importing `web.gunicorn_server` in a test** calls `gevent.monkey.patch_all()` and imports the whole web app. Before `importlib.import_module`, monkeypatch `gevent.monkey.patch_all` to a no-op, `setitem` a stub `web.server.app` into `sys.modules`, and `delitem` the server module. Then stub `GunicornApplication.run` and read `self.cfg` to see what gunicorn really loaded. `load_config` drops falsy option values.
- **mypy --strict with `--python-version 3.8`** needs `mypy<1.15`, plus `pytest<8`, `flask==2.0.3`, `click<8.1` and `werkzeug<2.1`. Newer versions of those packages use `match` statements, which a 3.8 target cannot parse. Use a /tmp config with `explicit_package_bases` and `namespace_packages`: the repo `mypy.ini` loads the `sqlmypy` plugin, and the worktree directory name is not a valid package name.
- **Ruff:** the repo has no ruff config, so the defaults flag the house style (single quotes, `%` formatting). Builders check with `--select E,F,W,I,B` and format with black 22.6 using `--skip-string-normalization`.
- **Live run without Postgres:** stub `create_app` in `sys.modules` and run the module with `runpy`. The script is `docs/modernisation/work/WP-2g-evidence/backend_gunicorn_server_live.sh`. Pass an older copy of the server file to get a baseline.

Related: [[py38-web-tests]], [[flask-local-test-env]]
