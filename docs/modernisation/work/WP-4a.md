---
wp: "4a"
title: "Settings and deployment loading"
status: building
owner_role: "core"
instances:
  - name: "core-4a"
    files:
      - harmony/core/**
      - config/__init__.py
      - config/settings.py
      - config/loader.py
      - config/harmony_demo/general.py
      - config/harmony_demo/ui.py
      - config/template/general.py
      - config/template/ui.py
      - tests/core/**
      - pyproject.toml
      - uv.lock
      - docs/modernisation/work/WP-4a.md
branch: "mig/WP-4a-settings-loading"
requirements: [BE-1, BE-2, SEC-3, INV-1, INV-2, INV-3]
contracts_consumed: []
contracts_changed: []
security_review: false
---

# WP-4a: Settings and deployment loading

Phase detail: `docs/modernisation/phase-4-decouple-core-from-flask.md` section 4a. Branched from `mig/integration` at `8638861`, which carries WP-3a (the `find_spec` config hook), WP-0b (refusal of default secrets) and WP-2f (uv, ruff, mypy, CI).

## Plan

Units, in order. Each line names the change and the check that ends it.

1. **Dependencies.** Add `pydantic` and `pydantic-settings` at the last releases that still support CPython 3.8 and PyPy 3.8, which the web and pipeline images run until WP-3b. Raise `typing_extensions` from 4.1.1 to the floor pydantic needs. Check: `uv lock --check`; `uv sync --locked`; the two packages import on CPython 3.8, 3.9, 3.13 and PyPy 3.8; golden 269 passed with 0 drift; `tests/core` green.
2. **`harmony.core.settings`.** A frozen pydantic-settings `Settings` read from the environment only (no `.env` file), with typed fields, `SecretStr` for secrets, and a fail-fast `load_settings()` that refuses unset, blank and default secrets (SEC-3, WP-0b) and a missing `DRUID_HOST`. `get_settings()` loads once per process. Check: failing tests first in `tests/core/test_core_settings.py`, then green.
3. **`config.settings` becomes a facade.** Its module attributes come from `get_settings()`; `getenv` and `require_secret` stay for their readers. The env reads in the deployment modules this WP owns (`OBJECT_STORAGE_ALIAS`, `MAPBOX_ACCESS_TOKEN`) move to `Settings`. Check: a parity test pins every facade attribute and warning against the old module for a matrix of environments; `test_settings_secret_key.py` unchanged and green.
4. **`harmony.core.deployment`.** `Deployment` (frozen dataclass of the per-deployment modules), `deployment_codes()` (the registry of every `config/<code>/`), and `load_deployment(code)`, cached per process. `config.VALID_MODULES` and `config.loader.import_configuration_module` delegate to it, so the Flask app, the golden harness and the scripts load deployments through one path. Check: a test builds `harmony_demo` and `template` with sockets disabled (phase check); attribute parity with the legacy loader; golden green.
5. **BE-1 guard.** An import-linter contract forbids `flask`, `fastapi` and `starlette` under `harmony.core`; a `tests/core` case runs it so CI enforces it with no workflow change. mypy strict on `harmony/core`. Check: the contract passes, and fails on a deliberate `import flask`.
6. **INV-1 / INV-2 / INV-3.** Golden (`record.py --check`), `tests/authz`, `tests/web`, the pipeline fixture suite, `tests/core` on CPython 3.8, 3.9, 3.13 and PyPy 3.8; the web app factory and a pipeline step start with `ZEN_ENV=harmony_demo`. Check: results match the before run on the base commit.

### Scope

- **In:** settings and deployment loading, the `config.settings` facade, env reads in core-owned deployment modules that are process constants read at import.
- **Deferred, with owner:**
  - `current_app.zen_config` call sites (about 40) move to `AppContext.deployment` in WP-4f, when the context exists. After unit 4 they already read a `Deployment`.
  - Call-time reads of `DATABASE_URL`, `SQLALCHEMY_DATABASE_URI` and `POSTGRES_*` (`db/postgres/common.py`, `util/flask.py`) go with `harmony.core.db` in WP-4b. `util/flask.py` writes `DATABASE_URL` into `os.environ` at run time, so reading it once per process now would change behaviour.
  - Druid credentials (`util/druid.py`), `guess_druid_host` and `LOG_DRUID_RESPONSES` go with the Druid client in WP-4c.
  - Backend-owned readers (`web/server/configuration/flask.py`, `web/server/routes/views/page_renderer.py`) keep reading `config.settings`; backend moves them in phase 5.
- **Coordination with live branches:**
  - WP-1h (`mig/WP-1h-export-renderer-core`) deletes `RENDERBOT_EMAIL` and `URLBOX_API_KEY` from `config/settings.py` and reads `RENDERER_URL` / `RENDER_WEB_ORIGIN` through `settings.getenv`. `Settings` gets neither removed name. The facade keeps the two legacy `getenv` lines verbatim until WP-1h deletes them, because `page_renderer.py` on `mig/integration` still reads them.
  - WP-2g's `LOG_FORMAT` and `LOG_LEVEL` stay read by `log/` (infra), which configures logging before settings load so that a settings failure can be logged. `Settings` does not define them.

## Contract changes

None. C-1 (`AppContext`) arrives in WP-4f and will hold `Settings` and `Deployment`.

## Requests

None yet.

## Log

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
