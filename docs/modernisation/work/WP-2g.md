---
wp: "2g"
title: "Structured logging"
status: review
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
      - "docker/entrypoint_web.sh"
      - "docker/web/scripts/initialize_new_container.sh"
      - "docker/web/scripts/run_web_gunicorn.sh"
      - "tests/infra/test_web_scripts_log_json.py"
      - "docs/modernisation/work/WP-2g.md"
  # Resumed by infra-7 after the host reboot; same branch, same files.
  - name: "backend-1"
    files:
      - "web/gunicorn_server.py"
  - name: "backend-2"
    files:
      - "web/server/app.py"
      - "web/server/workers/__init__.py"
      - "web/server/security/signal_handlers.py"
      - "tests/web/test_request_logging_wiring.py"
      - "docs/modernisation/work/WP-2g-evidence/backend2_wiring_live.py"
      - "docs/modernisation/work/WP-2g-evidence/backend2_wiring_live.jsonl"
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
- **Format** from `LOG_FORMAT` (`json` or `text`). Unset means `json` when `ZEN_PROD` is set and `text` otherwise. No image sets `ZEN_PROD` (only `yarn prod-server` does), so Compose sets `LOG_FORMAT` per service. Level from `LOG_LEVEL`, default `INFO`.
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
- [x] backend: wire unit 3 into the app. Today nothing outside tests calls it, so production requests get no `X-Request-ID` and tasks carry none. (a) In `web/server/app.py` `create_app()`, call `install_request_logging(app)` (from `log.flask_request`) last, so the middleware wraps every other `wsgi_app` wrapper. (b) In `web/server/workers/__init__.py` `create_celery()`, call `connect_celery_logging()` (from `log.celery_signals`). It runs in the web process, which publishes tasks, and in the worker, which runs them; `dispatch_uid` makes repeated calls harmless. (c) In `web/server/security/signal_handlers.py` `initialize_request_logger`, take the id from `log.context.current_request_id()` (falling back to `new_request_id()`) instead of `uuid4()`, so `g.request_id` and the `g.request_logger` field match the response header and the JSON lines. Proof: a `create_app()` test-client request returns `X-Request-ID` and its log lines carry it; a task published inside that request carries the id in its headers. (blocks `ready`, not review of the infra units)
- [ ] core: in `web/server/migrations/env.py`, drop `fileConfig(config.config_file_name, disable_existing_loggers=False)`, and the `[loggers]`, `[handlers]` and `[formatters]` sections of `alembic.ini` that only it reads. During `flask db upgrade` in `initialize_new_container.sh` it swaps the root handler for a plain-text stderr handler, so the web container's first lines break the phase check `docker compose logs web | jq`. `log` is already configured when `web.server.app` is imported. Keep `sqlalchemy.engine` at WARNING and `alembic` at INFO with `logging.getLogger(...).setLevel(...)`, as the ini did. The ini's root WARN gives way to `LOG_LEVEL`. Proof: `flask db upgrade` against a scratch database writes only JSON lines with `LOG_FORMAT=json`. (blocks `ready` for the startup lines; request and worker lines are already JSON)

## Log

- 2026-10-04 infra-6 unit 1: claimed WP-2g and wrote the plan; check: `ownership.py who` on every planned path, all infra or shared.
- 2026-10-04 infra-6 unit 2: `log/config.py` and `log/context.py` (JSON and text formatters, redaction, `LOG_FORMAT`/`LOG_STREAM`/`LOG_LEVEL`, excepthook), rotating files removed, `log` no longer imports `web`; check: `tests/infra/test_log_format.py` 39 passed on 3.9 and 3.8, `tests/web` 68 passed, ruff E/F/W/I/B clean, mypy --strict clean (3.13 and --python-version 3.8).
- 2026-10-04 infra-6 unit 3: `log/request_id.py` (WSGI middleware), `log/flask_request.py` (install plus loaded-user id), `log/celery_signals.py` (keep logging config, `request_id` task header, task context), warnings captured into logging; check: `tests/web/test_request_id_logging.py` 16 passed on the 3.8 web env (startup test skips on the host env, which lacks flask_migrate), whole `tests/web` plus `tests/infra/test_log_format.py` 122 passed on the host env; a mutation that drops the header fails the published-task test; ruff and mypy --strict clean; a request through the real `create_app()` test client shown in [unit3_real_app_request.jsonl](WP-2g-evidence/unit3_real_app_request.jsonl).
- 2026-10-04 infra-7 unit 4: `tests/web/test_gunicorn_logging.py` (access line JSON shape and response request id, path token redaction, `gunicorn.error` deferring to the root handler) against the `logconfig_dict` from unit 2; check: 3 passed with gunicorn[gevent] 20.0.4, and each of three mutations (drop the `gunicorn.error` entry, drop the response request id, drop path redaction) fails its test; whole `tests/web` plus `tests/infra/test_log_format.py` 125 passed, 1 skipped; ruff clean, mypy --strict clean on 3.13 and --python-version 3.8 (with `--ignore-missing-imports` for untyped flask and celery); live gunicorn with 2 gevent workers and 40 concurrent requests: 40 access lines with 40 distinct request ids, each matching its view line and response header, no query token, no malformed client id, nothing on stderr ([unit4_run_live.sh](WP-2g-evidence/unit4_run_live.sh), [unit4_gunicorn_gevent_live.jsonl](WP-2g-evidence/unit4_gunicorn_gevent_live.jsonl)). Wiring into `web/gunicorn_server.py` requested from backend.
- 2026-10-04 backend-1 request (branch `mig/WP-2g-structured-logging-backend`): `web/gunicorn_server.py` passes `'logconfig_dict': logging_config()` to gunicorn, and the file is now typed (imports sorted, `noqa: E402` after the gevent patch, `sys.exit(main())` became `main()` since `main` returns `None`); `tests/web/test_gunicorn_logging.py` gains a test that runs `main()` with gevent patching and `create_app` stubbed and asserts the real `GunicornApplication` config holds `logging_config()` as `logconfig_dict`, and the existing tests are annotated; check: the new test failed before the change (`{}` != the config) and passes after; whole `tests/web` plus `tests/infra/test_log_format.py` 127 passed on the 3.8 web env; ruff E/F/W/I/B and black 22.6 clean; mypy --strict clean on both files on 3.13 and --python-version 3.8 (`--ignore-missing-imports`); live `web/gunicorn_server.py` with a stub app and one gevent worker: before, gunicorn wrote plain text to stderr and no access lines; after, JSON `gunicorn.error` and `gunicorn.access` lines on stdout, each access line carrying its response's request id, no query token, nothing on stderr ([backend_gunicorn_server_live.sh](WP-2g-evidence/backend_gunicorn_server_live.sh), [after](WP-2g-evidence/backend_gunicorn_server_live.txt), [before](WP-2g-evidence/backend_gunicorn_server_base.txt)).
- 2026-10-04 infra-7: merged `mig/integration` (WP-0b, WP-0d and WP-3a; `log/config.py` conflict kept ours, since integration only dropped the dead `segment` logger that the rewrite already removes) and `mig/WP-2g-structured-logging-backend`; check: `tests/web` plus `tests/infra/test_log_format.py` 153 passed on a rebuilt 3.8 web env, `tests/infra` 106 passed on the host env, `tests/infra/test_browser_share.py` 79 passed on 3.13.
- 2026-10-04 infra-7 unit 4b (security review follow-up on the gunicorn wiring): reading gunicorn 20.0.4 turned up three leaks. `Error handling request <uri>` logs at ERROR with the client's whole query string. `NoMoreData`, `InvalidChunkSize` and `ChunkMissingTerminator` put raw request body bytes into messages and tracebacks. In text mode, access lines used gunicorn's own format: request line with query, referer, and the basic-auth user. Fixes in `log/config.py`: query strings stripped from every line `gunicorn.*` writes; the body echoes redacted everywhere, since they also surface in app tracebacks; text access lines built from the same method, path and status fields as JSON, with the response request id. Tests written first and seen failing (10 of 19): `tests/web/test_gunicorn_logging.py::test_access_lines_carry_no_query_header_or_cookie_secrets` (json and text; `token`, `api_key`, `password` and an arbitrary query value, `Authorization` Bearer and Basic with its user, `Cookie` with `session` and `accessKey`, a `Referer` with a token, `Set-Cookie`), `::test_error_lines_drop_query_strings`, `::test_error_lines_do_not_echo_request_bodies_or_headers` (five gunicorn errors, json and text), `::test_text_access_lines_carry_the_response_request_id`, plus body-echo cases in `tests/infra/test_log_format.py::test_redact_removes_secret_values`; check: 62 passed in those two files, `tests/web` plus `tests/infra/test_log_format.py` 173 passed on the 3.8 web env, ruff and mypy --strict clean (3.13 and 3.8), unit 4 live run unchanged (40 of 40, no query token, nothing on stderr).
- 2026-10-04 infra-7 unit 5: Compose sets `LOG_FORMAT=json` and `LOG_STREAM=stdout` for web and worker, `LOG_FORMAT=json` for `etl-pipeline` (logs stay on stderr), and `LOG_FORMAT=text` for web, worker and pipeline in the dev overlay. nginx gets `LOG_FORMAT_ESCAPE=json` and a `LOG_FORMAT` with the app's top-level keys plus `http.host`, `client_ip` and `user_agent`; it uses `$uri`, so there are no query strings, and the request id comes from the upstream's response header. `prod/browser_share` reads the JSON lines next to the old `vhost` lines, so sessions continue across the switch. The live run also showed that nginx-proxy runs nginx under forego, which puts `nginx.1     | ` in ANSI colours before every line, also in `docker logs` without a TTY. WP-0g's parser read no line of real `docker logs <nginx>` output in either format; it now strips that prefix as well as Compose's. Tests first, seen failing: `tests/infra/test_compose_logging.py` (9 failed), the JSON tests in `tests/infra/test_browser_share.py` (3 failed), and the forego test (2 failed). Check: `tests/infra` 119 passed on the host env, `tests/infra/test_browser_share.py` 93 passed on 3.13; ruff, ruff format and mypy --strict add no findings (WP-0g's existing EXE001/ISC004/RUF100 findings are unchanged); shellcheck clean. The rendered `docker compose config` diff against HEAD shows only the logging variables ([unit5_compose_config_diff.txt](WP-2g-evidence/unit5_compose_config_diff.txt)). A throwaway nginx built from the production service definition (`extends`, loopback port only) proxied to a stub upstream: 3 JSON access lines, each with the upstream's request id and a numeric status, a quoted user agent escaped correctly, no `SEKRIT` query value anywhere in the raw output, and `browser_share.py` on the raw `docker logs` output counts 2 sessions (Chrome 126, Firefox 115) ([unit5_nginx_check.sh](WP-2g-evidence/unit5_nginx_check.sh), [unit5_nginx_access.jsonl](WP-2g-evidence/unit5_nginx_access.jsonl), [rendered log_format](WP-2g-evidence/unit5_nginx_log_format.txt)). Deferred to the nginx routing WPs (WP-5a/5h): nginx lines still carry Flask-User reset and confirm tokens in `$uri`. Redacting them needs an http-level `map`, which nginx-proxy only takes from a `conf.d` file on the host. The old `vhost` format logged the same paths plus every query string.

- 2026-10-04 infra-7 unit 5b: the phase check is `docker compose logs web | jq`, and the web container's own startup scripts printed plain text. `docker/entrypoint_web.sh`, `docker/web/scripts/initialize_new_container.sh` and `docker/web/scripts/run_web_gunicorn.sh` now print JSON lines (`timestamp`, `level`, `logger` = script name, `message`) through a small `log_json` function. Tests first, seen failing (7 of 7): `tests/infra/test_web_scripts_log_json.py` (no plain `echo` left, each `log_json` writes one JSON line, and `run_web_gunicorn.sh` run through WP-0b's harness prints only JSON); check: those plus `tests/infra/test_run_web_gunicorn.py` 10 passed, shellcheck clean. Alembic's own text handler during `flask db upgrade` is requested from core under Requests.
- 2026-10-04 infra-7 unit 6: wiring requests filed under Requests: backend for the Flask install, Celery signals and one request id in `signal_handlers`; core for Alembic's logging config. Status set to review.
- 2026-10-04 backend-2 request (branch `mig/WP-2g-structured-logging-backend-2`): `create_app()` calls `install_request_logging(app)` last; `create_celery()` calls `connect_celery_logging()` (and is now typed); `initialize_request_logger` takes `current_request_id()`, falling back to `new_request_id()`, so `g.request_id` (now a `str`, read nowhere else) and the `g.request_logger` field match the header. Tests first in `tests/web/test_request_logging_wiring.py`, both seen failing before the change: a `create_app()` request (fresh interpreter, generated and forwarded ids) whose `X-Request-ID`, JSON view line and `g.request_id` agree, and a task published from a request after `create_celery()` and run by an in-process worker carrying the request id, task name and id. Each of three mutations (drop the install, drop the connect, revert to a fresh id) fails a test. Check: `tests/web` plus `tests/infra` 258 passed on the 3.8 web env (`test_browser_share.py` needs 3.13: 93 passed there); black 22.6 clean; ruff E/F/W/I/B and mypy --strict (`--python-version 3.8`) add no findings on the three legacy modules (mypy 130 to 127) and are clean on the new test; live `create_app()` run with a worker: header, view line, `g.request_id` and task line share one id, no secret placeholder in the output ([backend2_wiring_live.py](WP-2g-evidence/backend2_wiring_live.py), [backend2_wiring_live.jsonl](WP-2g-evidence/backend2_wiring_live.jsonl)). `test_request_id_logging.py::test_app_startup_logs_no_secret` still calls `install_request_logging` after `create_app`; the second wrap is harmless (it keeps the outer id), and the owner may drop that line.
- 2026-10-04 infra-7: merged `mig/WP-2g-structured-logging-backend-2` (fast-forward to a1d3a79) and dropped the now redundant `install_request_logging` from `test_app_startup_logs_no_secret`, which tests the real `create_app()` wiring; check: `tests/web` plus `tests/infra` 258 passed on the 3.8 web env, `tests/infra` 126 passed on the host env with gunicorn, `test_browser_share.py` 93 passed on 3.13, unit 4 live run unchanged.

## Evidence

Each link below is cited with its check in the Log above.
- Formats and redaction: `tests/infra/test_log_format.py`; a pipeline step's lines in [unit2_pipeline_step.jsonl](WP-2g-evidence/unit2_pipeline_step.jsonl).
- Request ids, Flask and Celery: `tests/web/test_request_id_logging.py`; a real `create_app()` request in [unit3_real_app_request.jsonl](WP-2g-evidence/unit3_real_app_request.jsonl); the app's own wiring in `tests/web/test_request_logging_wiring.py` and [backend2_wiring_live.jsonl](WP-2g-evidence/backend2_wiring_live.jsonl).
- gunicorn: `tests/web/test_gunicorn_logging.py`, including the leak tests from unit 4b; live gevent run [unit4_run_live.sh](WP-2g-evidence/unit4_run_live.sh) with [unit4_gunicorn_gevent_live.jsonl](WP-2g-evidence/unit4_gunicorn_gevent_live.jsonl); backend's `web/gunicorn_server.py` run [before](WP-2g-evidence/backend_gunicorn_server_base.txt) and [after](WP-2g-evidence/backend_gunicorn_server_live.txt).
- Compose and nginx: `tests/infra/test_compose_logging.py`, [unit5_compose_config_diff.txt](WP-2g-evidence/unit5_compose_config_diff.txt), live nginx [unit5_nginx_check.sh](WP-2g-evidence/unit5_nginx_check.sh) with [unit5_nginx_access.jsonl](WP-2g-evidence/unit5_nginx_access.jsonl).
- Browser share: `tests/infra/test_browser_share.py`.

Environments: the host env is `uv sync` on 3.9, run with `--with 'gunicorn[gevent]==20.0.4' --with 'setuptools<70'` for gunicorn. The 3.8 web env is `uv venv --seed --python 3.8`, then the venv's own `pip install -r requirements.txt -r requirements-web.txt 'pytest<8.4' freezegun`. `requirements-dev.txt` does not install on 3.8, and a hook blocks `uv pip`. The browser-share tests run on `uvx --python 3.13 --with pytest==8.4.2`.

Deferrals: OpenTelemetry traces and `/metrics` go with FastAPI in WP-5a (BE-8's other half), and the liveness and readiness endpoints too, since they live under `/api/v3`. Flask-User tokens in nginx `$uri` go to WP-5a/5h (see unit 5).

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
