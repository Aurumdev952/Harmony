---
name: request-logging-wiring
description: Testing WP-2g request-id and Celery logging wiring through create_app/create_celery; traps in the non-gunicorn create_app path, env leakage and mypy on Celery tasks
metadata:
  type: reference
---

Found while wiring WP-2g unit 3 into the app (2026-10-04).

- **`create_app()` outside gunicorn skips `_initialize_app`**: no Flask-User, no `app.login_manager`, no `register_for_signals`, no `create_celery`. A test that wants `initialize_request_logger` through `create_app` adds `LoginManager(app)` and `request_started.connect(initialize_request_logger, app)` itself. Run it in a fresh interpreter with `SQLALCHEMY_DATABASE_URI` set (else `build_flask_config` reads `POSTGRES_USER`).
- **Celery signal receivers are process-global**, keyed by `dispatch_uid='log.celery_signals'`. To prove a function connects them, `signal.disconnect(dispatch_uid=...)` on the four signals first; other tests connect them directly.
- **Do not export `LOG_FORMAT=json` in a test runner.** `tests/web/test_worker_refuses_default_secrets.py` inherits `os.environ` and expects a plain `RuntimeError:` last line on stderr.
- **mypy --strict and Celery:** `@app.task` is an untyped decorator even with celery installed. Use `task = app.task(name=...)(fn)` in typed tests. celery 5.4 needs `click>=8.1.2`, so the mypy env pins `click==8.1.3` instead of `click<8.1`.
- **Worktree guard:** a heredoc that also `cd`s, or `uvx --with 'click<8.1'` chained with `&&`, is refused. Write runner scripts under `/tmp` with the Write tool and call them alone.

Related: [[py38-web-tests]], [[gunicorn-server-checks]], [[celery-startup-checks]]
