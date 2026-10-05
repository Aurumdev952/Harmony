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
      - .github/dependabot.yml
      - prod/browser_share/**
      - tests/infra/**
      - tests/toolchain/**
      - docs/modernisation/work/WP-3b.md
      - docs/modernisation/work/WP-3b-evidence/**
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
2. **One CI lane** (done). `ci/tools313` and the `tests/infra` conftest guard are deleted; `tests/infra` joins `ci/pytest_suites.sh`; the strict mypy check of the standalone tools moves into the root config; `integration.yml` has one Python 3.13 job; uv moves to 0.12.23, and the setuptools build constraint carries its hashes (uv 0.12.16+, security's note on WP-2f); `lint-js` installs with `yarn install --frozen-lockfile` (security's low finding from the WP-2f confirmation, routed by the lead); `make test` follows. Check: actionlint, zizmor, the WP-0f policy script, and the job's commands locally, with one broken case making it exit non-zero.
3. **Web image on `python:3.13-slim-bookworm` with uv** (done; its PERF-7 claim waits on the core ijson request). Multi-stage: `uv sync --locked --no-install-project` then the app; runtime stage holds `.venv` and the app, running as a non-root user. One image serves web and worker. Check: `docker build --check`; the image builds; an import sweep inside it; `docker compose config --quiet` for every overlay; the web and worker containers start against the compose stack and the web healthcheck passes.
4. **Pipeline image on CPython 3.13 with uv, no PyPy** (done). The PyPy venv goes; `SetupEnvForPyPy` already falls back to the active venv when `venv_pypy3` is absent, so pipeline steps run on CPython with no pipeline-owned change. Check: the image builds; the pipeline fixture suite passes inside it; a `harmony_demo` step runs; wall-clock of the pipeline suite on CPython 3.13 against PyPy 3.9 recorded.
5. **Dev image on CPython 3.13** (done). The Python 3.9 source build and the PyPy download go; the dev Compose overlay drops the `venv_pypy3` volume. Check: the image builds; `make up DEV=1` brings up web with the dev overlay.
6. **Image workflows** (done). The image tag is sanitised for branch names containing `/` (WP-0f leftover). Check: actionlint and a simulated `run:` with `mig/WP-3b-cpython-313`.
7. **No pip inputs left** (done). Once no image installs `requirements*.txt`, they and `docker/export_requirements.py` (with its tests and `make requirements`) are deleted. Check: a repo grep finds no reader; `tests/infra` passes.
8. **Retire the Python 3.8 scaffolding** (done, added 2026-10-05). Once the images move, `[tool.ruff] target-version = "py38"` and the per-file targets (from `mig/ruff-target-py38`) go, so ruff takes 3.13 from `requires-python`. The CI step "Python 3.8 syntax (web image)", `ci/check_py38_syntax.py` and its test (from `mig/ci-py38-syntax-guard`) also go. Check: `tests/toolchain/test_ruff_target.py` fails before and passes after; ruff, mypy, actionlint, zizmor and the policy pass.

**Exit check (lead, 2026-10-05; met by units 3 and 8).** Until no image runs Python 3.8, builders and gates run `tests/web` on the 3.8 web environment as well as on 3.13. `py_compile` cannot replace this, because 3.8 parses some 3.9+ forms (a parenthesised `with` without `as`) as a tuple and fails only at run time. When the web image moves (this PR), `[tool.ruff] target-version = "py38"` from `mig/ruff-target-py38` changes to `py313`, or goes so that `requires-python` decides, and `tests/toolchain/test_ruff_target.py` changes to match.

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
- [ ] **core (blocks the PR, PERF-7): parse streamed Druid responses fast on 3.13 without losing Long.MIN_VALUE.** `db/druid/query_client.py` streams every `GroupByQueryBuilder` response (`streaming = True`) through `ijson.items(fp, 'item', use_float=True)`. Before this WP the web image built `ijson-bigint`'s C backend (`yajl2_c`). That fork's C code does not compile on 3.11+ (`PyGenObject has no member gi_code`), so on 3.13 ijson falls back to its pure-Python backend. `WP-3b-evidence/ijson_probe2.py`, 200,000 rows (19.6 MB): base image `yajl2_c` 0.20 s; this image `python` 3.31 s. The alternatives are wrong: upstream `ijson` 3.5.1's `yajl2_c` (0.14 s) and the `yajl2` ctypes backend over Debian's libyajl2 both fail with `integer overflow` on `-9223372036854775808`, which is the yajl bug the fork exists for. The stdlib `json` parser is fast and exact, but it does not stream. The choice is core's; infra keeps libyajl out of the image so ijson cannot pick the ctypes backend. Hosts with libyajl installed (this build host) get the ctypes backend in `uv sync` environments, so the golden suite here runs on it.
- [ ] **pipeline (non-blocking, after unit 4):** drop `SetupEnvForPyPy` from `util/pipeline/bash/common.sh` and its callers in `pipeline/{harmony_demo,template}/process/run/*`, and the `_pypyjson`/`__pypy__` branches in `data/pipeline/datatypes/base_row.py` and `data/pipeline/io/druid_writer.py`. Without `venv_pypy3` the function prints a warning and keeps the CPython venv, so nothing breaks meanwhile. Also the invalid escapes in `data/pipeline/scripts/fetch_database_tables.py` and `xlsx_to_csv.py`. FYI: `savReaderWriter` left the `pipeline` group; it cannot import on Python 3.10+ (`from collections import Iterable`) and nothing in the repository imports it.
- [ ] **qa (non-blocking):** `tests/pipeline/run.sh` defaults to 3.9 and says 3.12+ cannot import `config/`; `tests/pipeline/requirements.txt` pins `future==0.18.3`, which imports `imp` (gone in 3.12), and README line 29 says the same. On this branch the suite passes on 3.13 from the root lock (130 passed).
- [ ] **lead and human (before this branch merges):** the root `pyproject.toml` now needs uv 0.12.16 or later (hashed build constraints, `required-version`). The build host's `uv` is 0.12.5, and every uv command in a checkout of this branch stops with "Required uv version `>=0.12.16` does not match", including `uv run --no-project` from the repo root. Update uv on the host (`uv self update` to 0.12.23) and tell the other roles. The CI job is renamed "Python 3.13 - lint, types, tests" and the "Python 3.13 - standalone tools" job is gone; if branch protection lists check names, update it.
- [x] **lead / WP-2g core supporter: images built with uv compile bytecode at build time**, so a first start prints no compile-time SyntaxWarnings before logging is configured. The web image sets `UV_COMPILE_BYTECODE=1` for `.venv` and runs `python -m compileall` over the app code it copies (unit 3). The pipeline and dev images follow in units 4 and 5.
- [ ] **human (before deploying this image): the web and worker processes now run as uid 1000 (`zenysis`).** The entrypoint `docker/web/run_as_zenysis.sh` starts as root, hands `/data/output` (the directory and its `*.log*` files), `/data/output/zenysis_static` and `/zenysis/uploads` to uid 1000, and copies `/root/.mc/config.json` into the user's home. Then it drops root with `setpriv`. On a host this changes the owner of `${DATA_PATH}/output` (top level, logs, static files) and `${DATA_PATH}/ubuntu/uploads` to uid 1000, which is `ubuntu` on Ubuntu hosts. Nothing else on the host changes. If a host's uid 1000 is someone else, say so before deploying.
- [ ] **lead (non-blocking):** `scripts/watch/watch_util.py` invalid escape (SyntaxWarning); `.vscode/settings.json` excludes `venv_pypy3`.

## Log

- 2026-10-04 infra-3 unit 1a: `pyproject.toml` and `uv.lock` on CPython 3.13 (`14079e1`). Check: `uv lock --check` with uv 0.12.5 and 0.12.23; fresh-cache `uv sync --locked -v` builds 22 packages, all with setuptools 82.0.1 only; import sweep 722 OK / 50 ERR on 3.9 (base) and on 3.13, identical module by module and message by message; suites on 3.13: core 25, druid 1, druid_setup 79, graphql 5, infra 159, pipeline 130, toolchain 9, web 95 passed, golden 38 failed / 231 passed (core request); mypy "no issues found in 517 source files"; `ci/lint_python.sh mig/integration` passes; `flask db upgrade` then `flask db current` exit 0 on a scratch Postgres (base: `current` crashes).
- 2026-10-05 infra-3 resumed: rebased on `mig/integration` `8638861` (no conflicts); `uv lock --check` and the `flask db` check re-run green.
- 2026-10-05 infra-3 unit 2: one CI lane (`ci/tools313`, the `tests/infra` conftest guard and the `python-313` job deleted; `tests/infra` runs in `ci/pytest_suites.sh`; the standalone tools' strict mypy in the root config; uv 0.12.23 with hashed setuptools build constraint; `yarn install --frozen-lockfile`). Check: actionlint 0, zizmor 0, workflow policy OK, `uv lock --check`, lint gate and mypy (519 files) pass, suites as unit 1a plus `tests/infra` 159; broken cases exit 1 (below).

- 2026-10-05 infra-3: `mig/ruff-target-py38` for the lead (separate from WP-3b): `target-version = "py38"` plus `tests/toolchain/test_ruff_target.py`, head `0321c55` on `mig/integration` `3c9f5a3`.
- 2026-10-05 infra-3: `mig/ci-py38-syntax-guard` for the lead: `ci/check_py38_syntax.py` and a CI step on a pinned CPython 3.8.20, head `019538a` (merged at `61db9f8`).
- 2026-10-05 infra-3 unit 3: web image on `python:3.13.16-slim-bookworm` with uv 0.12.23, multi-stage, the app running as uid 1000. Check: `docker build --check` clean on both Dockerfiles; images build; import sweep identical to the base image module by module; `docker compose config --quiet` OK for 9 file sets; web and worker healthy on a throwaway stack with the prod overlay, and the same HTTP results as the base image (below). Open: the ijson request to core (PERF-7).
- 2026-10-05 infra-3 rebased on `mig/integration` `61db9f8` (ruff py38 target and the 3.8 syntax guard); one conflict in `pyproject.toml`, where unit 2 keeps the per-file targets until unit 8.
- 2026-10-05 infra-3 unit 4: pipeline image on `python:3.13.16-slim-bookworm` with uv, no PyPy. Check: `docker build --check`; image builds; fixture suite in the image 130 passed; import sweep identical to the base image; the harmony_demo `10_process` Zeus step gives byte-identical outputs to PyPy at 12, 100k and 1M rows, with CPython 2.3 times slower at 1M rows (below).
- 2026-10-05 infra-3 unit 5: dev image with uv-managed CPython 3.13.16, no Python 3.9 build, no PyPy, and Node 18.17.1 by checksum, because NodeSource's Node 14 repository fails signature checks. Check: `docker build --check`; image builds; dev overlay: database upgraded, web healthy, flask dev server answers, webpack compiles; `tests/infra/test_one_interpreter.py`.
- 2026-10-05 infra-3 unit 6: image workflows tag with a sanitised branch name. Check: `tests/infra/test_image_workflows.py` (10 failed before, 10 pass after); actionlint 0, zizmor 0, policy OK.
- 2026-10-05 infra-3 unit 7: `requirements*.txt`, `docker/export_requirements.py`, its tests and `make requirements` deleted; the pin policy and passlib/bcrypt check moved to `tests/infra/test_pyproject_pins.py`. Check: grep finds no reader outside history docs; pin test fails on an unpinned `toposort`; `tests/infra` passes.
- 2026-10-05 infra-3 unit 8: the Python 3.8 scaffolding retired (above). Check: suites as unit 2 (golden 38 failed / 231 passed, the core request; the rest pass); mypy 518 files; lint gate, actionlint, zizmor, policy.

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

### Unit 2: one CI lane

- **Scripts.** `WP-3b-evidence/workflow_policy.py` is WP-0f's workflow policy (SHA pins with tag comment, `ubuntu-24.04`, `permissions: {}` plus per-job grants, no `${{ }}` in `run:`, `GH_TOKEN` only on "List changed files" steps), now in the repo so it can be re-run: `uv run docs/modernisation/work/WP-3b-evidence/workflow_policy.py`. `WP-3b-evidence/flask_db_check.sh <tree> <python>` is unit 1a's `flask db` check.
- **Workflows.** actionlint 1.7.12 (release binary, `sha256sum -c` against its checksums file) with shellcheck 0.11.0: exit 0, no output. zizmor 1.30.1 `--offline .github/`: no findings (12 suppressed, the same count as `mig/integration`). Policy: `policy OK (3 workflows)`; a copy of `integration.yml` with `ubuntu-latest` and `${{ github.head_ref }}` in a `run:` gives 3 breaches, exit 1.
- **The job's commands, uv 0.12.23, `CI=true`.** `uv lock --check` exit 0; `ci/lint_python.sh mig/integration` exit 0; `uv run --locked mypy`: "no issues found in 519 source files" (517 plus the two tools); `ci/pytest_suites.sh`: core 25, druid 1, druid_setup 79, graphql 22, infra 159, pipeline 130, toolchain 9, web 95 passed; golden 38 failed / 231 passed (the core request, unchanged), so the script exits 1 and names `tests/golden`.
- **Strict tools check.** Appending `def untyped(x): return x` to `browser_share.py` makes `uv run --locked mypy` exit 1 (`no-untyped-def`). mypy 1.3's typeshed types `TextIOWrapper`'s buffer as `IO[bytes]`, which `GzipFile` is not, so `read_lines` casts; mypy 2.4 (the old lane) accepted it. Moving the app to mypy 1.11+ finds 6 or 7 errors in `web/server` (core and backend files), so the app stays on 1.3 here.
- **Hashed build constraint.** Fresh cache, uv 0.12.23 (`/tmp/wp3b/build_constraint_hash.sh`): `uv sync --locked` exit 0, 22 `Installing build requirement: setuptools==82.0.1`; with both setuptools hashes zeroed in a copy of `pyproject.toml` and `uv.lock`, the sync exits 1 with `Hash mismatch for setuptools==82.0.1`. The hashes are PyPI's for the 82.0.1 wheel and sdist. uv 0.12.5 cannot parse the table form, so `[tool.uv] required-version = ">=0.12.16"` makes older uv stop with "Required uv version `>=0.12.16` does not match the running version" instead of a parse error.
- **`yarn install --frozen-lockfile`.** `node:18.17` (pinned digest) over a copy of `package.json` and `yarn.lock`, `--ignore-scripts`: exit 0. With `left-pad` added to `package.json` only: exit 1, "Your lockfile needs to be updated".
- **The lead's alembic request.** The lead asked to pin alembic to the last release Flask-Migrate 2.5.2 supports. Unit 1a moved Flask-Migrate to 2.7.0 instead: 2.5.2 needs alembic below 1.5.0 (1.4.3, from 2020), which is below the `alembic>=1.7.1` floor and does not support Python 3.13. On the rebased branch `flask db upgrade` exits 0 (head `2b730c14f514`) and `flask db current` exits 0 and prints `2b730c14f514 (head)`.

### Unit 3: web image

Scripts are under `WP-3b-evidence/`; `web_stack/run.sh` is the runtime harness (`TAG=u3|base run.sh up|probe|down`).

- **Images.** `docker/web/Dockerfile_web-server`: a build stage (slim plus git and gcc, uv copied from `ghcr.io/astral-sh/uv:0.12.23` by digest) runs `uv sync --locked --no-install-project --no-default-groups --group web`, which is the same package set the old image took from `requirements.txt` plus `requirements-web.txt`. The runtime stage (slim plus lz4) holds `.venv` and the app code, owned by root, and compiles that code. `docker/web/Dockerfile_web` adds the client, the scripts and the `run_as_zenysis` entrypoint. Its ARGs now have the Compose defaults, which clears two `InvalidDefaultArgInFrom` warnings. Built as `local/wp3b-infra3/harmony-web{-server,}:u3`: 934 MB. No gcc, git or uv in the runtime image.
- **Interpreter and C speedups.** In the image: Python 3.13.16 at `/zenysis/.venv/bin/python`, `markupsafe._speedups` and `sqlalchemy.cresultproxy` present, gevent 26.7.0, gunicorn 20.0.4, celery 5.4.0. The ijson backend is pure Python (core request).
- **Import sweep** (`sweep_image.sh`, as uid 1000, no network): branch image 689 OK / 64 ERR, base image (`mig/integration`, Python 3.8, run as root) 689 OK / 64 ERR, with the same module list, statuses and messages (`join` shows no differing line). The 64 errors are pipeline-only packages and code the web image never carried.
- **Compose** (`compose_config.sh`, dummy env): `config --quiet` OK for the base file alone, with prod, local, dev, db+local and db+prod, and for the db, pipeline and build files.
- **Runtime, with an upgrade from a root image simulated** (`web_stack/run.sh`; rootless Docker, so host-owned files look root-owned in the container). Postgres (tmpfs), the WP-2c Druid stub, redis and hasura run with `docker-compose.yaml`, `local` and `prod`. nginx stays off and nothing is published. `ZEN_OFFLINE=1`, because the stub answers metadata only. The bind mounts start with a stale `zenysis_static/build/stale.js`, a `zenysis.log`, an upload and a mode-600 mc config, all owned by "root".
  - `up --wait`: web and worker healthy.
  - Processes: web PID 1, gunicorn master and 4 workers all run as `zenysis`. The worker's 18 celery processes run as `zenysis`; only the `celery status` healthcheck, run by `docker exec`, is root.
  - `compose run --rm web ./scripts/create_user.py ... --site_admin` (the Makefile's command, through the entrypoint) creates the admin.
  - HTTP from inside web, branch and base images alike: `/` 200, `/login` 200, anonymous `/api2/user` 401, `/static/build/version.txt` 404 (nginx serves it in production), login 200, then `/api2/user` 200 (1), `/api2/role` 200 (20), `/overview` 200, `/data-catalog` 200 (`web_stack/probe-u3.txt`, `probe-base.txt`).
  - Ownership afterwards: the log files, `zenysis_static` (stale file replaced) and uploads are uid 1000; `/data/output/logs` (hasura's) is untouched; `~zenysis/.mc/config.json` is 600 and readable by the app; the beat schedule is `/tmp/celerybeat-schedule`. The worker command now passes `--schedule=/tmp/celerybeat-schedule`, because the default (the working directory `/zenysis`) is not writable by the app user.
  - The only error line in either image's logs is the 404 above.
- **Checks:** `tests/infra` 159 passed (`test_dockerfiles` pins); shellcheck clean on `run_as_zenysis.sh`; `uv lock --check`.

### Unit 4: pipeline image

- **Image.** Build stage as for web but with `--group pipeline` into `/zenysis/venv`, the path `docker/entrypoint_pipeline.sh`, `make bash-pipeline` and deployments activate. The runtime stage is slim plus ca-certificates, curl, wget, git, jq, lz4, pigz, postgresql-client, proj-bin, sqlite3, unzip and vim, with mc from the old verified download. It drops build-essential, cmake, gfortran, every `-dev` package, the deadsnakes Python 3.9 and PyPy. The `zenysis` system user and `USER zenysis` are kept; the venv is owned by root. 1.37 GB. In the image: CPython 3.13.16, numpy 2.1.3, pandas 2.2.3, shapely 2.0.7, pyproj 3.7.2, no `pypy3`, `python3.9`, gcc or `venv_pypy3`.
- **Fixture suite in the image** (`pipeline/pipeline_in_image.sh`, uid 1000 as in `docker-compose.pipeline.yaml`; uv layers only pytest 8.4.2 and hypothesis 6.91.0 over `/zenysis/venv`, and pandas resolves to `/zenysis/venv`): 130 passed.
- **Import sweep** (`pipeline/sweep_pipeline.sh`, dirs config data db log models util web pipeline scripts): branch 759 OK / 76 ERR; base image (`mig/integration`, its CPython 3.9 venv) 759 OK / 76 ERR; `diff` of the two TSVs is empty.
- **harmony_demo step, CPython 3.13 against PyPy** (`pipeline/zeus_compare.sh`, `pipeline/zeus_compare.txt`). `process/run/00_yellow_fever/10_process` runs inside each image as the entrypoint runs it: venv activated, then the step's own `SetupEnvForPyPy`. In the base image that switches to PyPy 3.8.13; in this image it prints its "no venv_pypy3" warning and stays on CPython 3.13.16. Input: the yellow_fever fixture repeated to N rows; three runs each; outputs compared by md5 of the sorted rows, `locations.csv` and `fields.csv`.

  | Rows | PyPy 3.8 (base) | CPython 3.13 (branch) | Outputs |
  |---|---|---|---|
  | 12 | 294-338 ms | 519-709 ms | identical |
  | 100,000 | 415-508 ms | 677-698 ms | identical |
  | 1,000,000 | 1.68-1.75 s | 3.81-4.09 s | identical |

  Per-row Python is about 2.3 times slower without PyPy's JIT, as phase 3 expects until WP-8d's Polars rewrite. The fixture suite itself (tiny inputs) is faster on CPython: on this host from the base tree, PyPy 3.9 36.4 s and CPython 3.9 14.8 s wall.

### Unit 5: dev image

- **Image** (`local/wp3b-infra3/harmony-dev-web:u5`). uv 0.12.23 copied from its image; `uv python install 3.13.16` into `/opt/python`; `uv sync --locked --no-install-project` (every group) into `/app/venv`. In the image: CPython 3.13.16 at `/app/venv/bin/python`, pandas 2.2.3, pytest 8.4.2, mypy 1.3.0, node v18.17.1, yarn 1.22.19, no `venv_pypy3` or `pypy3`. Jammy's `python3` is installed because node-gyp needs a Python when `yarn install` builds node-pty. The Python 3.9 source build is what used to provide it.
- **Node.** On `mig/integration` the dev image does not build: `curl https://deb.nodesource.com/setup_14.x | bash` now stops with `NO_PUBKEY 1655A0AB68576280` (the repository is "not signed"). Node 18.17.1, the release `Dockerfile_web-client` and the lint-js job use, comes from nodejs.org, checked against `SHASUMS256.txt` for x64 and arm64. yarn is pinned to 1.22.19, the client image's. Node 24 (FE-11) stays with its own WP.
- **Volumes.** `docker-compose.dev.yaml` renames `web_venv` to `web_venv_cp313`. Docker fills a named volume from the image only while the volume is empty, so a developer's existing `web_venv` (the 3.9 venv) would otherwise shadow the new one. `web_venv_pypy3` goes.
- **`make up DEV=1`** (`dev_stack/run.sh`, throwaway project, nothing published, Postgres and Redis in tmpfs, the WP-2c Druid stub, `ZEN_OFFLINE=1`): the database steps of `upgrade_dev_database.sh`, run directly because its `git rev-parse` cannot see this worktree's git directory inside the container, then `flask db upgrade`; redis, hasura and web come up healthy. Inside web: CPython 3.13.16 `/app/venv/bin/python`; `/` 200, `/login` 200, `/api2/user` 401; the flask dev server is "Running on http://0.0.0.0:5000/"; webpack "Compiled successfully". The named volumes `wp3b-infra3-dev_web_venv_cp313` and `wp3b-infra3-dev_web_node_modules` remain on the build host (scratch, safe to delete).
- **Structure:** `tests/infra/test_one_interpreter.py` checks that every Dockerfile uses one `python:3.13.x-slim-bookworm` digest matching `requires-python`, that the dev image installs the same release, that there is one uv image, and that no Dockerfile or Compose file installs PyPy or runs `pip install`. The last check fails on the pre-WP Dockerfiles: 15, 19 and 3 matches.

### Units 6 to 8

- **Unit 6.** `web.yml` and `pipeline.yml` compute `image_tag` once in `prepare` (characters outside `[A-Za-z0-9_.-]` become `-`, cut at 128) and every build job uses `needs.prepare.outputs.image_tag`. The test runs the step's `run:` with `bash -e`: `mig/WP-3b-cpython-313` gives `mig-WP-3b-cpython-313`, and a 200-character name gives 128 characters.
- **Unit 7.** The pin policy, with an allowance list no longer carrying `pandas>=1.3,<2.0` (now `==2.2.3`), has a new check that the allowance has no stale entries. Git sources must be pinned to 40-hex SHAs. The bcrypt check runs passlib in the locked environment. Making `toposort==1.5` loose fails `test_new_requirements_are_pinned_exactly`.
- **Unit 8.** `ruff check --show-settings` shows `unresolved_target_version = 3.13` and empty per-file targets for `web/server/app.py` and `prod/browser_share/browser_share.py`.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
