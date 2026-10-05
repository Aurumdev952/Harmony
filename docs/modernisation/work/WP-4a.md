---
wp: "4a"
title: "Settings and deployment loading"
status: review
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

- [x] infra: run `make requirements` on this branch (or in WP-3b) so `requirements.txt` picks up `pydantic==2.10.6` and `pydantic-settings==2.8.1`, `requirements-web.txt` and `requirements-pipeline.txt` pick up `typing_extensions==4.12.2`, and `requirements-dev.txt` picks up `import-linter==2.5.2` and `grimp==3.13` (unit 5). The images install from those files, and CI's sync check fails until they match `pyproject.toml`. Blocks merge (INV-1, INV-8), not the build units.
- [x] infra: add `COPY harmony harmony` to `docker/web/Dockerfile_web-server` (next to `COPY config config`) and `COPY harmony ./harmony` to `docker/pipeline/Dockerfile` (next to `COPY config ./config`). Both images copy an explicit list of top-level directories, and `config/__init__.py` and `config/settings.py` now import `harmony.core`. Without this, the web server, the worker and every pipeline step fail at `import config` with `ModuleNotFoundError: harmony`. The dev image mounts the repo (`.:/app`) and needs nothing. Blocks merge (INV-1).
- [ ] lead: merging with WP-1h conflicts on the last lines of `config/settings.py`. WP-1h deletes `RENDERBOT_EMAIL` and `URLBOX_API_KEY`, and this WP changed the `DRUID_HOST` line above them. Resolve by keeping this branch's file without those two lines. `tests/core/test_settings_facade.py` passes either way, and WP-1h's `tests/core/test_settings_render.py` passes on the result (simulated, see Evidence).

## Log

- 2026-10-04 core-4a unit 1: `pydantic==2.10.6`, `pydantic-settings==2.8.1` in the root dependencies; `typing_extensions` 4.1.1 to 4.12.2 in the web and pipeline groups (pydantic 2.10 needs >= 4.12.2); `uv lock` adds annotated-types, pydantic-core 2.27.2 and python-dotenv. check: `uv lock --check` and `uv sync --locked` clean; pydantic 2.10.6 + pydantic-settings 2.8.1 import on CPython 3.8, 3.9, 3.13 and PyPy 3.8 (PyPy 3.9 has no pydantic-core wheel at the latest release; no image runs it); golden 269 passed, `record.py --check` 85 cases 0 drift; every CI suite green (core 25, web 95, druid 1, druid_setup 79, graphql 22, pipeline 129 + 1 skipped, toolchain 9).
- 2026-10-05 core-4a (resumed) unit 2 `090ef57`: `harmony/core/settings.py`. `Settings` is a frozen pydantic-settings model read only from the environment: names are case-sensitive, and there is no `.env` file and no secrets directory. `DEFAULT_SECRET_KEY` is a `SecretStr`, refused when unset, blank or `changeme`. One `refuse_default_secret` serves both this check and the facade's `require_secret`. `DRUID_HOST` is required but may be empty, as before. The optional settings are `NOREPLY_EMAIL`, `SUPPORT_EMAIL`, `REDIS_HOST` (default ''), `HASURA_HOST`, `OBJECT_STORAGE_ALIAS` and `MAPBOX_ACCESS_TOKEN`. `load_settings()` raises one `RuntimeError` that names every problem. It never chains the `ValidationError`, because that carries raw input values (INV-6). `get_settings()` caches per process. mypy runs strict for `harmony.core` (a pyproject override, since mypy 1.3 has no per-module `strict`) with the `pydantic.mypy` plugin. check: `tests/core/test_core_settings.py` failed at collection first, then 45 passed on CPython 3.9 (lock), 3.8 and 3.13 and on PyPy 3.8 and 3.9; `uv run --locked mypy` clean (520 files); ruff check and format clean.
- 2026-10-05 core-4a unit 3 `48ee2a3`: `config/settings.py` is a facade over `get_settings()`. `getenv` and `require_secret` stay. A new `setting(name)` returns a `Settings` value and logs the same "Environment variable X not set" warning that `getenv` did. `config/{harmony_demo,template}/general.py` read `OBJECT_STORAGE_ALIAS` through it, and `ui.py` reads `MAPBOX_ACCESS_TOKEN`. check: `tests/core/test_settings_facade.py` compares the facade with `tests/core/legacy/config_settings_ea33d9d.py`, a verbatim copy of the module before this WP. It runs both in fresh interpreters over 7 environments and compares attributes, warnings, `getenv` and `require_secret`. Before the change, the parity cases passed against the old module (an oracle check) and the 2 intended differences failed until implemented. core 84, golden 269 with `record.py --check` 0 drift, web 95.
- 2026-10-05 core-4a unit 4 `5eddfa0`: `harmony/core/deployment.py`.
  - `Deployment` is a frozen dataclass of the 11 modules readers reach through `zen_config`: `aggregation_rules`, `aggregation`, `calculated_indicators`, `data_status`, `datatypes`, `druid`, `filters`, `general`, `indicators`, `pipeline_sources`, `ui`, in the legacy import order.
  - `deployment_codes()` is the registry: every `config/*/general.py` except `template`.
  - `load_deployment(code)` is cached. It accepts the registry plus `template` and raises `ValueError` otherwise.
  - `config.VALID_MODULES` is now `list(deployment_codes())`, and `config.loader.import_configuration_module` returns `load_deployment(...)`. So `app.zen_config` (Flask app and golden harness) and the two scripts get a `Deployment`.

  check: `tests/core/test_core_deployment.py` failed at collection first, then 13 passed. `harmony_demo` and `template` load with socket connect, `getaddrinfo` and `create_connection` refused. Each field is the same object that the legacy `__import__(..., fromlist=...)` loader returned and that the `config.<name>` alias resolves to. Bad codes are refused. All 8 CI suites green.
- 2026-10-05 core-4a unit 5 `48ee251`: import-linter 2.5.2 (dev group) with a forbidden contract in `pyproject.toml`: `harmony.core` must not import `flask`, `fastapi` or `starlette`. The graph includes the legacy packages (`config`, `data`, `db`, `log`, `models`, `util`, `web`), so an import path through them also counts (872 files, 0.4 s). check: `tests/core/test_core_boundaries.py` 6 passed. The contract is KEPT on the tree. It is BROKEN on a copy of `harmony/core` that adds `import flask`, `from flask import current_app`, `from fastapi import FastAPI` or `import starlette.requests`, and on one that adds `from web.server import app_base` (transitive). `uv lock --check` clean.
- 2026-10-05 core-4a unit 6 `9e9aab9`: invariant runs (see Evidence). The parity test now ignores `RENDERBOT_EMAIL` and `URLBOX_API_KEY` on both sides, so it passes before and after WP-1h merges. Status set to review.
- 2026-10-05 infra (branch `mig/WP-4a-settings-loading-infra`) `429a2b1`: both infra requests done.
  - **Images copy `harmony`.** `COPY harmony harmony` in `docker/web/Dockerfile_web-server` and `COPY harmony ./harmony` in `docker/pipeline/Dockerfile`, next to `config`. A new test in `tests/infra/test_dockerfiles.py` walks the module-level imports from every file under `config/` and fails when a Python image does not copy a package they reach. It failed first on both images, naming only `harmony`. The reached set is `config data db harmony log models util web`.
  - **`make requirements`.** `requirements.txt` gains `pydantic==2.10.6` and `pydantic-settings==2.8.1`. `requirements-web.txt` and `requirements-pipeline.txt` move to `typing_extensions==4.12.2`. `requirements-dev.txt` gains `import-linter==2.5.2`. `grimp` is transitive, so it stays in `uv.lock` only, like every other transitive dependency. Before this, `tests/infra/test_requirements_export.py::test_committed_requirements_match_pyproject` failed. It passes now, and `uv lock --check` is clean.
  - **The new pins broke the PyPy pipeline image (fixed).** Jammy's `pypy3` is 7.3.9, which is Python 3.8. pydantic-core 2.27.2 has PyPy wheels only for 3.9 and 3.10. pip therefore took the sdist, which needs maturin and Rust, and the build stopped at `ModuleNotFoundError: No module named 'maturin'`. The local PyPy 3.8 run in unit 1 passed only because uv compiled the sdist with the host's cargo. The fix is a `pypy-wheels` stage that builds the pp38 wheel with Rust 1.83 (`rust:1.83.0-slim-bookworm`, pinned by digest) and maturin 1.8.1. The PyPy install then uses it through `--find-links`. Rust stays out of the runtime image. A test pins the stage's `PYDANTIC_CORE_VERSION` to the `uv.lock` version. Old numpy (1.15.4) still builds on PyPy.
  - **Renderer image (WP-1h).** No change needed. It copies only `harmony/worker/renderer`, which imports neither `config` nor `harmony.core`.

  check: the web-server and pipeline images were built from the branch, and every smoke ran with `--network none`, test-only secrets, `ZEN_ENV=harmony_demo` and the dummy `DRUID_HOST`/DB URL.
  - **Web-server, before the fix** (the Dockerfile at `d6ecedd`): `import config` fails with `ModuleNotFoundError: No module named 'harmony'`.
  - **Web-server, after the fix:** `import config` and `load_deployment('harmony_demo')` print `['harmony_demo'] Deployment`. `import web.background_worker` (the WP-0b worker smoke) succeeds. The app factory (non-gunicorn `create_app`, cache, renderers, query data, `_register_routes`) gives 314 routes, matching unit 6. With `DEFAULT_SECRET_KEY=changeme`, the image refuses with the SEC-3 `RuntimeError`.
  - **Pipeline image:** both venvs import `config`, `config.settings` and `harmony.core.settings`: CPython 3.9.25 and PyPy 3.8.13. `util.local_script_wrapper` (the path validate steps use) imports on CPython. PyPy `load_deployment` succeeds. An empty `DEFAULT_SECRET_KEY` is refused on PyPy.
  - `tests/infra` 164 passed (CPython 3.13 lane), `tests/toolchain` 9 passed, `uv lock --check` and `docker/export_requirements.py --check` clean, and ruff is clean on the test file.
  - **Not run:** a dev image build and `make up DEV=1` (the dev image installs the same files on CPython 3.9 and PyPy 3.9, which have wheels). QA's stack smoke covers the gunicorn path.
  - **Pre-existing, not caused by this WP:** the pipeline image has no `requirements-web.txt`, so `web.server.app` (and `flask_jwt_extended`) cannot be imported there. `web.server.app_base` can be.
- 2026-10-05 core-4a: fast-forwarded to infra's `314496e`, then merged `mig/integration` at `1c8578e` (merge `a9a8436`): ruff now targets py38, plus decisions 0005/0006. The merge was clean; WP-1h is not on integration yet, so `config/settings.py` did not conflict. Invariant runs repeated on the merge (see Evidence, "After the infra and integration merge"). Status stays review.

### Recorded differences (INV-1, for reviewer acceptance)

No query result or authorisation decision changes: golden shows 0 drift, and no policy code was touched. The differences are in startup and logging:

1. **Missing `DRUID_HOST`.** Before, this raised `KeyError('DRUID_HOST')` after four optional-setting warnings. Now it raises `RuntimeError: DRUID_HOST is not set; refusing to start.` before any warning. No reader catches either exception. Pinned in `test_missing_druid_host_stops_the_import_before_any_warning`.
2. **Refused `DEFAULT_SECRET_KEY` together with a missing `DRUID_HOST`.** Same `RuntimeError` and message as before, plus a second line naming `DRUID_HOST`. Pinned.
3. **`config/template/ui.py`.** `MAPBOX_ACCESS_TOKEN` was `os.environ['MAPBOX_ACCESS_TOKEN']`, a `KeyError` when unset. It is now `None` plus the warning, as `harmony_demo` always behaved. The template is not a deployment, but new deployments copied from it now start without a Mapbox token, like `harmony_demo`.
4. **`config.loader.import_configuration_module`.**
   - It returns a `Deployment` instead of the `config.<code>` package. Every module attribute a reader uses is the same object as before.
   - An unknown or empty code raises `ValueError` (was `ModuleNotFoundError`).
   - A deployment missing one of the 11 modules now fails at load instead of at first attribute access. No in-tree deployment lacks one.
   - `config.<code>.calculated_indicator_defs` is no longer an attribute. Nothing read it, and `calculated_indicators` still imports it.
5. **Log records.** For the four optional settings and the two deployment-module settings, the record now names `setting` as its function instead of `getenv` (`settings.py:setting:NN`). Level and message are unchanged.

### Notes for later WPs

- The phase file lists a `calendar` module for `Deployment`. There is none: calendar settings are `aggregation.CALENDAR_SETTINGS`.
- `ZEN_ENV` stays a call-time read in `config/__init__.py` and in `config.loader`. The import hook runs before settings can load, and scripts import `config` without secrets. WP-4f should build `AppContext.deployment` from an explicit code.
- **WP-3b removal item.** Remove the pipeline image's `pypy-wheels` build stage when the images move to CPython 3.13. That covers the Rust 1.83 base pinned by digest, maturin 1.8.1, the `--find-links` install of the pp38 pydantic-core wheel, and the version-drift test that ties the stage's `PYDANTIC_CORE_VERSION` to `uv.lock` (in `tests/infra/test_dockerfiles.py`). The stage exists only because pydantic-core 2.27.2 has no PyPy 3.8 wheel and Jammy's `pypy3` is 7.3.9 (Python 3.8). If PyPy goes first (WP-8d), it can go then.
- `tests/authz` does not exist on this base (`mig/integration` at `8638861`). So INV-3 rests on two facts: no authorisation code changed, and `tests/web` (95 tests, including the JWT and render-route guards) passes unchanged.

## Evidence

All results are on head `9e9aab9` unless stated. The base for comparisons is `ea33d9d` (unit 1).

- **CI suites** (`ci/pytest_suites.sh -q`, CPython 3.9 lock): core 103 (was 25), druid 1, druid_setup 79, golden 269, graphql 22, pipeline 129 + 1 skipped, toolchain 9, web 95. "all 8 suites passed".
- **INV-2 golden:** `uv run python tests/golden/record.py --check` reports "85 cases, 0 fixture files would change" after every unit and on the head. `pytest tests/golden` gives 269 passed both before (base) and after.
- **Lint and types:**
  - `ruff check --select E9,F63,F7,F82 .`, plus `ruff check` and `ruff format --check` on the 15 changed Python files, pass.
  - `uv run --locked mypy` reports "Success: no issues found in 520 source files". `harmony/core` is strict: a probe `def f(x)` in `harmony/core` fails it.
  - `uv run --locked lint-imports --no-cache` reports "Contracts: 1 kept, 0 broken."
  - `uv lock --check` clean.
- **Image runtimes:**
  - **CPython 3.8 (web image).** With the image requirements (`requirements.txt` + `requirements-web.txt`, `typing_extensions` raised to 4.12.2, plus the two pydantic pins), `tests/core` gives 97 passed. `test_core_boundaries.py` was deselected because import-linter needs Python 3.9 or later (it is a dev tool only). This run covers the facade parity and the no-network deployment loads on 3.8.
  - **PyPy 3.8 (pipeline image).** The full pipeline requirements do not build locally: the numpy 1.15.4 sdist needs `distutils.msvccompiler`, and the image builds it differently. Instead I ran `tests/core/test_core_settings.py` (45 passed) and a smoke that imports `log`, `config`, `config.settings` and `harmony.core.deployment` with `ZEN_ENV=harmony_demo`. Results: `VALID_MODULES == ['harmony_demo']`; the facade values and the six warnings are as before; the secret does not appear in `repr(get_settings())`; an unset `DEFAULT_SECRET_KEY` fails with the SEC-3 message. **Correction (infra):** pydantic-core 2.27.2 has no PyPy 3.8 wheel. These local PyPy 3.8 runs passed only because uv compiled the sdist with the host's Rust; the image cannot do that, so it needed the `pypy-wheels` stage infra added. Infra's in-image PyPy 3.8.13 smoke is the evidence for that runtime.
  - **PyPy 3.9 (the dev image's pipeline venv).** pydantic-core 2.27.2 installs from a wheel (`--no-build`), and `test_core_settings.py` gives 45 passed.
  - **CPython 3.13.** `test_core_settings.py` gives 45 passed.
- **INV-1 web app factory.** Setup: `ZEN_ENV=harmony_demo`, dummy `DATABASE_URL`, `DRUID_HOST` and `DEFAULT_SECRET_KEY`, no services.
  - Steps: `create_app()` on the non-gunicorn path, then `initialize_cache`, `_initialize_template_renderer`, `_initialize_email_renderer`, `_initialize_query_data` and `_register_routes`. This is the path `util/local_script_wrapper` uses, and so the path the pipeline validate steps use.
  - Result: I ran the same script on the head and on a `git archive ea33d9d` tree, with the same venv. The JSON digests differ only in `zen_config_type` (`module` before, `Deployment` after). Both have the same 11 module names, renderer modules and locales (`am br en fr pt vn`), query-data digest `861cf207b186f983`, and 314 routes with digest `cce1c637398313a1`.
  - Not run: the gunicorn path, which needs Postgres and Druid. QA should include it in the `make up DEV=1` smoke run after the infra Dockerfile request lands.
- **WP-1h merge simulated.** With `RENDERBOT_EMAIL` and `URLBOX_API_KEY` deleted from the facade, `tests/core/test_settings_facade.py` plus WP-1h's `tests/core/test_settings_render.py` gave 15 passed. The deletion was reverted afterwards.
- **Not done here:** `tests/authz` is absent on this base, and there is no running stack.

### After the infra and integration merge (merge `a9a8436`)

- **CI suites** (`ci/pytest_suites.sh -q`): core 103, druid 1, druid_setup 79, golden 269, graphql 22, pipeline 129 + 1 skipped, toolchain 10 (gains integration's `test_ruff_target.py`), web 95. "all 8 suites passed". The infra lane (`uv run --project ci/tools313 --locked pytest tests/infra`) gives 164 passed.
- **Golden:** `record.py --check` reports "85 cases, 0 fixture files would change".
- **Lint and types:** `ruff check --select E9,F63,F7,F82 .` passes, and `ruff check` / `ruff format --check` pass on the WP's 15 changed Python files under the new py38 target. `mypy` reports "no issues found in 520 source files". `lint-imports --no-cache` reports "1 kept, 0 broken". `uv lock --check` is clean.
- **Startup digest:** same script, same base tree. The diff against `ea33d9d` is still only `zen_config_type` (`module` before, `Deployment` after). Routes (314), renderer modules, locales and the query-data digest are identical.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
