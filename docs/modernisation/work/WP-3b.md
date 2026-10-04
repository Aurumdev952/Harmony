---
wp: "3b"
title: "One CPython 3.13 interpreter everywhere"
status: building
owner_role: "infra"
instances:
  - name: "infra-3"
    files:
      - pyproject.toml
      - uv.lock
      - requirements*.txt
      - docker/**
      - docker-compose*.yaml
      - .dockerignore
      - Makefile
      - ci/**
      - .github/workflows/**
      - tests/infra/**
      - tests/toolchain/**
      - docs/modernisation/work/WP-3b.md
branch: "mig/WP-3b-cpython-313"
requirements: [INV-1, INV-2, INV-8, SEC-9, QA-4]
contracts_consumed: []
contracts_changed: []
security_review: false
---

# WP-3b: One CPython 3.13 interpreter everywhere

Phase detail: `docs/modernisation/phase-3-python-and-dependency-floor.md` section 3b. Branched from `mig/integration` at `15bdde3`, which carries WP-3a (the `find_spec` config hook) and WP-2f (uv, ruff, mypy, the two CI lanes).

## Plan

Units, in order. Each line names the change and the check that ends it.

1. **The root lock moves to CPython 3.13.** `requires-python = "==3.13.*"`; every pin that has no CPython 3.13 build or fails at import on 3.13 moves to the lowest release that works; PyPy markers and the PyPy numpy pin go; the lock-only psycopg2 override goes; build constraints are re-derived from a fresh-cache sync; `flask db current` works again (the lead's request from WP-2g). Check: `uv lock --check`; fresh-cache `uv sync --locked`; an import sweep of every first-party module on 3.13 matches the 3.9 sweep; every suite under `tests/` passes on 3.13, golden with `record.py --check` at 0 drift and the pipeline suite at 130; `flask db upgrade` and `flask db current` on a scratch Postgres.
   - 1a, the lock (done). 1b, golden green on 3.13: waits on core's pandas 2 fixes (Requests).
2. **One CI lane.** `ci/tools313` and the `tests/infra` conftest guard are deleted; `tests/infra` joins `ci/pytest_suites.sh`; the strict mypy check of the standalone tools moves into the root config; `integration.yml` has one Python 3.13 job; uv moves to 0.12.23, and the setuptools build constraint carries its hashes (uv 0.12.16+, security's note on WP-2f); `lint-js` installs with `yarn install --frozen-lockfile` (security's low finding from the WP-2f confirmation, routed by the lead); `make test` follows. Check: actionlint, zizmor, the WP-0f policy script, and the job's commands locally, with one broken case making it exit non-zero.
3. **Web image on `python:3.13-slim-bookworm` with uv.** Multi-stage: `uv sync --locked --no-install-project` then the app; runtime stage holds `.venv` and the app, running as a non-root user. One image serves web and worker. Check: `docker build --check`; the image builds; an import sweep inside it; `docker compose config --quiet` for every overlay; the web and worker containers start against the compose stack and the web healthcheck passes.
4. **Pipeline image on CPython 3.13 with uv, no PyPy.** The PyPy venv goes; `SetupEnvForPyPy` already falls back to the active venv when `venv_pypy3` is absent, so pipeline steps run on CPython with no pipeline-owned change. Check: the image builds; the pipeline fixture suite passes inside it; a `harmony_demo` step runs; wall-clock of the pipeline suite on CPython 3.13 against PyPy 3.9 recorded.
5. **Dev image on CPython 3.13.** The Python 3.9 source build and the PyPy download go; the dev Compose overlay drops the `venv_pypy3` volume. Check: the image builds; `make up DEV=1` brings up web with the dev overlay.
6. **Image workflows.** The image tag is sanitised for branch names containing `/` (WP-0f leftover). Check: actionlint and a simulated `run:` with `mig/WP-3b-cpython-313`.
7. **No pip inputs left.** Once no image installs `requirements*.txt`, they and `docker/export_requirements.py` (with its tests and `make requirements`) are deleted. Check: a repo grep finds no reader; `tests/infra` passes.

Units 1 to 5 change the lock and the images that install it, so the branch builds every image again only from unit 5 on. They merge as one pull request.

## Contract changes

None.

## Requests

Each item names the owner, the change, and what it blocks. Reproduce on this branch with `uv sync --locked`, then the command given.

- [ ] **core (blocks unit 1b, and so the PR): make the query shaping work on pandas 2.2 / numpy 2.1 with 0 golden drift.** `uv run pytest tests/golden` gives 38 failed, 231 passed. All 85 cases still post the recorded Druid queries (Evidence), so every failure is in response shaping under `web/server/query/`:
  1. `visualizations/hierarchy.py:217` `.drop('index', 'columns')`: pandas 2 takes no positional `axis` (TypeError). Cases `hierarchy_*` and `policy_hierarchy`.
  2. `data_quality/outliers_box_plot.py:58` `Series.iteritems()` was removed; `.items()`. Cases `dq_outliers_box_plot`, `policy_dq_outliers_box_plot`.
  3. `data_quality/data_quality_report.py:236` `pd.to_datetime(..., format=DRUID_DATE_FORMAT)` is now strict and rejects the `T00:00:00.000Z` suffix (ValueError). Cases `dq_data_quality`, `policy_dq_data_quality`.
  4. `visualizations/map.py:72` `df.to_dict('records', data_point_generator)`: the `into` argument no longer works as a row generator (KeyError on the lat/lon column). Cases `map_by_municipality`, `policy_map`.
  5. Row order only (same rows, different order; checked by sorting every list) in 12 cases: `bar_graph_sum_by_state_month`, `calc_last_value`, `calc_window`, `dq_reporting_completeness_line_graph`, `group_granularity_{day,quarter,week}`, `line_graph_bump_chart_quarter`, `line_graph_heat_tiles_week`, `line_graph_time_by_state`, `table_disaggregated`, `policy_table_disaggregated`. Order is visible in tables and charts, so INV-2 needs it unchanged.

  Suggested: branch `mig/WP-3b-cpython-313-core` from this branch, list the files under a `core-*` instance here, and keep the fixes to `web/server/query/**`. Other pandas users (`util/analysis`, `util/dataprep`, `web/server/routes/views/*`) import on 3.13 but have no suite; a grep for removed pandas 2 / numpy 2 APIs found only the four sites above.
- [ ] **backend (blocks unit 3's runtime claim): `collections` ABC aliases, removed in Python 3.10, raise AttributeError at call time.** No suite covers them, so they pass import and the suites. Start with a failing test (QA-1).
  - `web/server/util/util.py:253-256,373,379,404`: `collections.Mapping`, `collections.Iterable` → `collections.abc.*`;
  - `web/server/potion/managers.py:128`: `collections.Mapping` (Potion update path).
  - Low: `web/server/util/data_catalog.py:205` invalid escape `"\^"` (SyntaxWarning on 3.12+, an error in a later Python); `web/dev_reloader.py:16` still watches `venv_pypy3`.
- [ ] **pipeline (non-blocking, after unit 4):** drop `SetupEnvForPyPy` from `util/pipeline/bash/common.sh` and its callers in `pipeline/{harmony_demo,template}/process/run/*`, and the `_pypyjson`/`__pypy__` branches in `data/pipeline/datatypes/base_row.py` and `data/pipeline/io/druid_writer.py`. Without `venv_pypy3` the function prints a warning and keeps the CPython venv, so nothing breaks meanwhile. Also the invalid escapes in `data/pipeline/scripts/fetch_database_tables.py` and `xlsx_to_csv.py`. FYI: `savReaderWriter` left the `pipeline` group; it cannot import on Python 3.10+ (`from collections import Iterable`) and nothing in the repository imports it.
- [ ] **qa (non-blocking):** `tests/pipeline/run.sh` defaults to 3.9 and says 3.12+ cannot import `config/`; `tests/pipeline/requirements.txt` pins `future==0.18.3`, which imports `imp` (gone in 3.12), and README line 29 says the same. On this branch the suite passes on 3.13 from the root lock (130 passed).
- [ ] **lead (non-blocking):** `scripts/watch/watch_util.py` invalid escape (SyntaxWarning); `.vscode/settings.json` excludes `venv_pypy3`.

## Log

- 2026-10-04 infra-3 unit 1a: `pyproject.toml` and `uv.lock` on CPython 3.13 (`14079e1`). Check: `uv lock --check` with uv 0.12.5 and 0.12.23; fresh-cache `uv sync --locked -v` builds 22 packages, all with setuptools 82.0.1 only; import sweep 722 OK / 50 ERR on 3.9 (base) and on 3.13, identical module by module and message by message; suites on 3.13: core 25, druid 1, druid_setup 79, graphql 5, infra 159, pipeline 130, toolchain 9, web 95 passed, golden 38 failed / 231 passed (core request); mypy "no issues found in 517 source files"; `ci/lint_python.sh mig/integration` passes; `flask db upgrade` then `flask db current` exit 0 on a scratch Postgres (base: `current` crashes).

## Evidence

Logs and scripts are under `/tmp/wp3b/` on the build host; the commands are below so a reviewer can rerun them.

### Unit 1a: the lock

- **Baseline (`15bdde3`, CPython 3.9, its own lock):** `ci/pytest_suites.sh` equivalent, `CI=true`: core 25, druid 1, druid_setup 79, golden 269, graphql 5, pipeline 130 (13.2 s), toolchain 9, web 95; all passed.
- **Pins moved, and why.** Every package was checked for a CPython 3.13 linux wheel; packages with only an sdist were built, then every first-party module was imported.

  | Package | Was | Now | Reason |
  |---|---|---|---|
  | numpy | 1.21.0 (PyPy 1.15.4) | 2.1.3 | first minor with 3.13 wheels |
  | pandas | >=1.3,<2.0 | 2.2.3 | first with 3.13 wheels; pandas 1.5 cannot use numpy 2 |
  | shapely / pyproj | 1.8 / 3.4.1 | 2.0.7 / 3.7.2 | 3.13 wheels; pyproj 3.4 fails to build (`pkg_resources`) |
  | psycopg2-binary | 2.8.5 (lock 2.8.6) | 2.9.13 | 3.13 wheels; the lock-only override goes |
  | lz4, python-rapidjson | 4.3.2, 1.9 | 4.4.5, 1.17 | 3.13 wheels |
  | MarkupSafe | 0.23 | 2.0.1 | 0.23 imports `collections.Mapping`; Jinja2 2.11 needs `soft_unicode` (gone in 2.1) |
  | Jinja2 | 2.10.1 | 2.11.3 | 2.10 imports `collections.Mapping` |
  | Flask | 1.0.1 | 1.0.4 | 1.0.2 and earlier import `collections.MutableMapping` |
  | attrs | 21.4.0 | 24.1.0 | before 22.1, slotted `related.immutable` classes break zero-argument `super()` on 3.11+ (`GranularityExtraction.to_druid`); 24.1 is the first to support 3.13 |
  | boto3 | 1.16.25 | 1.43.108 | botocore 1.19 vendors a six whose importer 3.12 no longer calls |
  | future | 0.18.3 | 1.0.0 | imports `imp` |
  | pydruid | git 2017 commit | 0.6.9 | subclasses `collections.MutableSequence`; all 85 golden cases post identical queries |
  | Flask-Migrate | 2.5.2 | 2.7.0 | `flask db current` crashed (below) |
  | selenium, pytest-selenium | 4.5.0, 4.0.1 | removed | nothing imports them; trio 0.24 breaks on 3.13; pytest-selenium was already disabled |
  | savReaderWriter | unpinned | removed | `from collections import Iterable` at import; nothing imports it |

  Werkzeug 0.16.1, WTForms 2.1, SQLAlchemy 1.3.24 (pure-Python build), flask-user 0.6.21, flask-login 0.4.1, celery 5.4.0 and gunicorn 20.0.4 import on 3.13 unchanged (units 3 and 5 run them), and mypy 1.3 runs; phases 3c to 3e move the Flask-era pins.
- **Druid queries (INV-2).** `/tmp/wp3b/golden_queries.py` wraps the recorded broker and compares the posted queries of every case even when shaping later fails: "queries identical: 85, differ: 0".
- **Golden responses.** `/tmp/wp3b/golden_order.py`: the 12 drifting cases that return 200 differ in row order only; the other 11 cases fail with HTTP 500 at the four sites in the core request.
- **Import sweep.** `docs/modernisation/work/WP-0d-evidence/import_sweep.py` over `config data db log models util web pipeline graphql`, one process, dummy env (`/tmp/wp3b/sweep.sh`): 722 OK / 50 ERR on both interpreters; `diff` of the two TSVs (paths normalised) is empty.
- **Removed stdlib APIs.** A grep for APIs Python 3.13 removed (`collections` ABC aliases, `imp`, `asyncore`, `distutils`, `cgi`, `pipes`, `getargspec`, ...) over first-party code finds only the backend sites in Requests. Over site-packages, every hit is guarded by a version check or sits in a module nothing imports (`coloredlogs.converter`, `redis.commands.graph`, Cython's build helpers).
- **`flask db` (lead's request, WP-2g).** `/tmp/wp3b/flask_db_check.sh <tree> <python>`: throwaway `postgres:15.19-alpine` (pinned digest, tmpfs) plus a Druid coordinator stub answering `[]`.
  - base `15bdde3`, 3.9, Flask-Migrate 2.5.2, alembic 1.14.1: `flask db upgrade` exit 0 (head `2b730c14f514`); `flask db current` exit 1, `TypeError: current() got an unexpected keyword argument 'head_only'`.
  - this branch, 3.13, Flask-Migrate 2.7.0, alembic 1.14.1: `upgrade` exit 0 (head `2b730c14f514`), `current` exit 0 and prints `2b730c14f514 (head)`.
  - Choice: Flask-Migrate 2.5 passes `head_only=`, which alembic removed in 1.5.0, so the alternative was alembic 1.4.3 (2020), below the `alembic>=1.7.1` floor and with no 3.13 support. Flask-Migrate 2.6 dropped `head_only` and 2.7.0 is the last 2.x; its requirements are unchanged (Flask >= 0.9, alembic >= 0.7).
- **Pipeline suite on 3.13:** 130 passed in 8.9 s from the root lock (3.9: 13.2 s).
- **SyntaxWarnings on 3.12+** (`compileall -W error::SyntaxWarning`): four files, routed in Requests.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
