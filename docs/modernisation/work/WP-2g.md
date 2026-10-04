---
wp: "2g"
title: "Structured logging"
status: building
owner_role: "infra"
instances:
  - name: "infra-6"
    files:
      - "log/**"
      - "tests/infra/test_log_format.py"
      - "tests/infra/test_compose_logging.py"
      - "tests/infra/test_browser_share.py"
      - "tests/web/test_request_id_logging.py"
      - "tests/web/test_gunicorn_logging.py"
      - "prod/browser_share/browser_share.py"
      - "docker-compose.yaml"
      - "docker-compose.dev.yaml"
      - "docker-compose.pipeline.yaml"
      - "docs/modernisation/work/WP-2g.md"
branch: "mig/WP-2g-structured-logging"
requirements: [BE-8]
contracts_consumed: []
contracts_changed: []
security_review: false
---

# WP-2g: Structured logging

Phase detail: [phase-2-test-harness-and-toolchain.md, section 2g](../phase-2-test-harness-and-toolchain.md); observability in [03-target-architecture.md](../03-target-architecture.md).

## Plan

BE-8 has two halves. This WP delivers JSON lines on stdout with a request id. OpenTelemetry traces go with FastAPI in WP-5a, which BE-8 also names.

Constraints found while reading the code:
- `log` is imported by about 120 modules across web, worker, pipeline and scripts, and configures logging at import. The web image runs CPython 3.8, the pipeline image PyPy and CPython 3.9, so `log/` stays standard-library only and 3.8-compatible. No new dependency.
- `log/log.py` imports `web.server.environment` only to read `ZEN_PROD`. The new code reads the environment itself, so `log` no longer depends on `web`.
- Every Flask request already gets a `uuid4` request id and user id in `initialize_request_logger` (`web/server/security/signal_handlers.py`), but the old format string never printed them.
- Celery hijacks the root logger unless a `setup_logging` receiver is connected. Gunicorn only writes access lines when an access log or `logconfig_dict` is configured; today neither is, so production has no gunicorn access lines at all.
- `nginxproxy/nginx-proxy` (1.11.6, as pinned by WP-0b) takes `LOG_FORMAT` and `LOG_FORMAT_ESCAPE` from the environment. It does not forward `X-Request-ID`, and deployments run Compose against a remote `DOCKER_HOST`, so a repo-relative `conf.d` bind mount would not exist on the host. nginx therefore logs the app's id from the response header (`$upstream_http_x_request_id`) instead of setting one.

Design:
- **One configuration** in `log/config.py`, applied by `configure_logging()` when `log` is imported. One stream handler on the root logger, so the app, Celery, gunicorn, werkzeug and libraries share it. `ZenysisLogger` propagates to it. The rotating files under `/data/output` go.
- **Format** from `LOG_FORMAT` (`json` or `text`). Unset means `json` when `ZEN_PROD` is set (the web image) and `text` otherwise. Level from `LOG_LEVEL`, default `INFO`.
- **Stream** from `LOG_STREAM` (`stdout` or `stderr`), default `stderr` as today. Pipeline steps capture other scripts' stdout (`SOURCES=($(generate_pipeline_sources.py ...))` in `pipeline/*/process/run/90_shared/*`) and `config.settings` logs warnings at import, so logging to stdout by default would put log lines into those arrays (INV-1). Compose sets `LOG_STREAM=stdout` for web and worker, whose stdout carries no data; that is where BE-8 applies. Docker collects both streams, so `docker compose logs` shows pipeline lines either way.
- **JSON keys:** `timestamp` (ISO 8601, UTC, milliseconds), `level`, `logger`, `message`, `source`, `deployment` (`ZEN_ENV`), `request_id` and `user_id` when bound, `task` and `task_id` inside a Celery task, `exc_info` when there is an exception, `http` on access lines.
- **Context** in `contextvars` (`log/context.py`): it follows threads started inside a request only when copied, and it is per greenlet under gevent (greenlet 3 keeps a context per greenlet).
- **Request id:** a WSGI middleware (`log/request_id.py`) takes a well-formed `X-Request-ID` (1 to 128 of `A-Za-z0-9._:-`) or generates a uuid4 hex, binds it for the request and echoes it in the response header. `log/flask_request.py` installs it on a Flask app and adds a user-id provider that reads the user Flask-Login has already loaded, so logging never triggers a database load.
- **Celery:** `log/celery_signals.py` connects `setup_logging` (Celery keeps our handler), `before_task_publish` (adds `request_id` to the task headers), and `task_prerun`/`task_postrun` (binds the header's request id, the task name and id in the worker; eager tasks inherit the caller's context).
- **Gunicorn:** `GUNICORN_LOGCONFIG` routes `gunicorn.error` and `gunicorn.access` to the same handler. Access records become JSON with `http.method`, `path`, `status`, `bytes` and `duration_s`, and the request id comes from the response header.
- **nginx:** `LOG_FORMAT` writes the same top-level keys plus `http.host`, `client_ip` and `user_agent`. `prod/browser_share` (WP-0g) learns to read it.
- **Secrets:** every formatted line, including tracebacks, passes a redaction pass for bearer and basic credentials, JWTs, URL passwords, cookies, `key=value` or `"key": value` pairs whose key names a password, secret, token or key, and Flask-User token paths. That is a backstop; leaks found by grep are routed to their owners below.
- **Uncaught exceptions** go through `sys.excepthook` to the root logger at ERROR, so a startup refusal is one JSON line whose message carries the variable name, never the value.

Units:
1. Claim and plan. Check: `ownership.py who` on every planned path.
2. `log/config.py` and `log/context.py`: formatters, redaction, `configure_logging()`, excepthook; drop the rotating files. Tests in `tests/infra/test_log_format.py`. Check: pytest on the host env (3.9) and the web env (3.8), ruff, mypy strict on `log/`.
3. Request id middleware, Flask install and Celery propagation. Tests in `tests/web/test_request_id_logging.py`: echo, generate, reject malformed, user id, eager task, a task published through the memory broker and run by an in-process worker, and no secret value in any log line from app setup and login attempts. Check: the same static checks, plus a request through the test client showing a JSON line.
4. Gunicorn logconfig and access shape. Tests in `tests/web/test_gunicorn_logging.py`. Check: a live gunicorn gevent run with concurrent requests; every access line carries its own request id.
5. Compose `LOG_FORMAT` for web, worker and pipeline (`text` in the dev overlay), the nginx `LOG_FORMAT`, and the browser-share JSON reader. Check: `docker compose config` diff shows only the logging variables, a throwaway nginx proxies to a stub and writes a JSON line carrying the upstream's id, and the browser-share tests pass.
6. Requests for the backend and core wiring, then review.

## Contract changes

None.

## Requests

- [x] backend: in `web/gunicorn_server.py`, add `'logconfig_dict': logging_config()` (from `log.config`) to `options` in `main()`. Without it gunicorn keeps its own stderr handler and writes no access lines at all; with it, `gunicorn.error` and `gunicorn.access` go through the WP-2g handler as JSON, carrying the response's request id (proven live in unit 4). `GunicornApplication.load_config` overrides `Application.load_config`, so `GUNICORN_CMD_ARGS` cannot set it from Compose. (blocks the production effect of unit 4; units 5 and 6 proceed)
## Log

- 2026-10-04 infra-6 unit 1: claimed WP-2g and wrote the plan; check: `ownership.py who` on every planned path, all infra or shared.
- 2026-10-04 infra-6 unit 2: `log/config.py` and `log/context.py` (JSON and text formatters, redaction, `LOG_FORMAT`/`LOG_STREAM`/`LOG_LEVEL`, excepthook), rotating files removed, `log` no longer imports `web`; check: `tests/infra/test_log_format.py` 39 passed on 3.9 and 3.8, `tests/web` 68 passed, ruff E/F/W/I/B clean, mypy --strict clean (3.13 and --python-version 3.8).
- 2026-10-04 infra-6 unit 3: `log/request_id.py` (WSGI middleware), `log/flask_request.py` (install plus loaded-user id), `log/celery_signals.py` (keep logging config, `request_id` task header, task context), warnings captured into logging; check: `tests/web/test_request_id_logging.py` 16 passed on the 3.8 web env (startup test skips on the host env, which lacks flask_migrate), whole `tests/web` plus `tests/infra/test_log_format.py` 122 passed on the host env; a mutation that drops the header fails the published-task test; ruff and mypy --strict clean; a request through the real `create_app()` test client shown in [unit3_real_app_request.jsonl](WP-2g-evidence/unit3_real_app_request.jsonl).
- 2026-10-04 infra-7 unit 4: `tests/web/test_gunicorn_logging.py` (access line JSON shape and response request id, path token redaction, `gunicorn.error` deferring to the root handler) against the `logconfig_dict` from unit 2; check: 3 passed with gunicorn[gevent] 20.0.4, and each of three mutations (drop the `gunicorn.error` entry, drop the response request id, drop path redaction) fails its test; whole `tests/web` plus `tests/infra/test_log_format.py` 125 passed, 1 skipped; ruff clean, mypy --strict clean on 3.13 and --python-version 3.8 (with `--ignore-missing-imports` for untyped flask and celery); live gunicorn with 2 gevent workers and 40 concurrent requests: 40 access lines with 40 distinct request ids, each matching its view line and response header, no query token, no malformed client id, nothing on stderr ([unit4_run_live.sh](WP-2g-evidence/unit4_run_live.sh), [unit4_gunicorn_gevent_live.jsonl](WP-2g-evidence/unit4_gunicorn_gevent_live.jsonl)). Wiring into `web/gunicorn_server.py` requested from backend.
- 2026-10-04 backend-1 request (branch `mig/WP-2g-structured-logging-backend`): `web/gunicorn_server.py` passes `'logconfig_dict': logging_config()` to gunicorn, and the file is now typed (imports sorted, `noqa: E402` after the gevent patch, `sys.exit(main())` became `main()` since `main` returns `None`); `tests/web/test_gunicorn_logging.py` gains a test that runs `main()` with gevent patching and `create_app` stubbed and asserts the real `GunicornApplication` config holds `logging_config()` as `logconfig_dict`, and the existing tests are annotated; check: the new test failed before the change (`{}` != the config) and passes after; whole `tests/web` plus `tests/infra/test_log_format.py` 127 passed on the 3.8 web env; ruff E/F/W/I/B and black 22.6 clean; mypy --strict clean on both files on 3.13 and --python-version 3.8 (`--ignore-missing-imports`); live `web/gunicorn_server.py` with a stub app and one gevent worker: before, gunicorn wrote plain text to stderr and no access lines; after, JSON `gunicorn.error` and `gunicorn.access` lines on stdout, each access line carrying its response's request id, no query token, nothing on stderr ([backend_gunicorn_server_live.sh](WP-2g-evidence/backend_gunicorn_server_live.sh), [after](WP-2g-evidence/backend_gunicorn_server_live.txt), [before](WP-2g-evidence/backend_gunicorn_server_base.txt)).
## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
