---
wp: "3b"
title: "One CPython 3.13 interpreter everywhere"
status: review
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
  # Supporting role, on mig/WP-3b-cpython-313-core-2. Its removal of ijson-bigint
  # from pyproject.toml and uv.lock sits in infra-3's claim.
  - name: "core-1"
    files:
      - db/druid/json_stream.py
      - db/druid/query_builder.py
      - db/druid/query_client.py
      - web/server/query/**
      - tests/druid/test_export_pandas_order.py
      - tests/druid/test_druid_response_parsing.py
      - tests/web/server/query/**
  # Supporting role, on mig/WP-3b-cpython-313-backend (merged at 512c6ba).
  - name: "backend-1"
    files:
      - web/dev_reloader.py
      - web/server/potion/managers.py
      - web/server/util/data_catalog.py
      - web/server/util/util.py
      - tests/web/test_collections_abc_call_paths.py
  # Supporting role, on mig/WP-3b-cpython-313-qa (merged at 45291b6).
  - name: "qa-1"
    files:
      - tests/contract/stack/compose.yaml
      - tests/contract/stack/init.sh
      - tests/contract/stack/stack.sh
      - tests/contract/test_stack_image_tag.py
      - tests/golden/README.md
      - tests/golden/harness.py
branch: "mig/WP-3b-cpython-313"
requirements: [INV-1, INV-2, INV-8, SEC-9, QA-4]
contracts_consumed: []
contracts_changed: []
# The lead asked for a security gate (2026-10-06): the web entrypoint starts as root,
# chowns host paths and drops to uid 1000 (docker/web/run_as_zenysis.sh).
security_review: true
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
9. **Merge the supporting branches and `mig/integration`** (done, 2026-10-06). Core's `-core-2` (`ab37cab`) and backend's branch (`23f6f20`), then `mig/integration` `7c34bca` and, as it moved, `290cd65`; re-lock with uv 0.12.23; rebuild the web, worker and pipeline images. Check: every suite, golden `record.py --check`, lint, mypy, `uv lock --check`, import sweeps and call probes in the images against images built from `mig/integration`, the web stack probe, `flask db upgrade` and `current`.
10. **Merge fallout in the images** (done). `compileall` in the web-server image covers `harmony/`, which WP-4a copied in but did not compile; the PyPy wheel drift test goes with the stages it guarded; the stale "No yajl" note goes. Check: `tests/infra/test_dockerfiles.py` fails before and passes after.
11. **Stack-marked tests in CI** (done). Job `python-stack` runs `ci/pytest_suites.sh -m stack` on `ubuntu-24.04`, so WP-0k's Postgres clock test (`tests/web/usernames/test_token_clock_postgres.py`, marked `stack`, starts its own pinned Postgres) runs once it lands. Check: `tests/infra/test_ci_stack_job.py` fails before and passes after; the job's command locally; the same selection over WP-0k's tree runs the clock test.
12. **The locked environment passes `uv pip check`** (done). The `dataclasses` backport (Python 3.6 only) leaves the `pipeline` group. Check: a new pin test fails before and passes after; `uv pip check` is clean in both images.

**Exit check (lead, 2026-10-05; met by units 3 and 8).** Until no image runs Python 3.8, builders and gates run `tests/web` on the 3.8 web environment as well as on 3.13. `py_compile` cannot replace this, because 3.8 parses some 3.9+ forms (a parenthesised `with` without `as`) as a tuple and fails only at run time. When the web image moves (this PR), `[tool.ruff] target-version = "py38"` from `mig/ruff-target-py38` changes to `py313`, or goes so that `requires-python` decides, and `tests/toolchain/test_ruff_target.py` changes to match.

Units 1 to 5 change the lock and the images that install it, so the branch builds every image again only from unit 5 on. They merge as one pull request.

## Contract changes

None.

## Requests

Each item names the owner, the change, and what it blocks. Reproduce on this branch with `uv sync --locked`, then the command given.

- [x] **core (blocks unit 1b, and so the PR): make the query shaping work on pandas 2.2 / numpy 2.1 with 0 golden drift.** Done by core-1, 2026-10-05, `d9382b0` on `mig/WP-3b-cpython-313-core-2`: golden 269 passed, no fixture changed. The four crash sites are fixed as listed. The row-order cases have one cause, `export_pandas` date filling: pandas 2.2 sorts every outer merge by its keys, even with `sort=False`. Evidence: "Core: pandas 2 shaping". `uv run pytest tests/golden` gives 38 failed, 231 passed. All 85 cases still post the recorded Druid queries (Evidence), so every failure is in response shaping under `web/server/query/`:
  1. `visualizations/hierarchy.py:217` `.drop('index', 'columns')`: pandas 2 takes no positional `axis` (TypeError). Cases `hierarchy_*` and `policy_hierarchy`.
  2. `data_quality/outliers_box_plot.py:58` `Series.iteritems()` was removed; `.items()`. Cases `dq_outliers_box_plot`, `policy_dq_outliers_box_plot`.
  3. `data_quality/data_quality_report.py:236` `pd.to_datetime(..., format=DRUID_DATE_FORMAT)` is now strict and rejects the `T00:00:00.000Z` suffix (ValueError). Cases `dq_data_quality`, `policy_dq_data_quality`.
  4. `visualizations/map.py:72` `df.to_dict('records', data_point_generator)`: the `into` argument no longer works as a row generator (KeyError on the lat/lon column). Cases `map_by_municipality`, `policy_map`.
  5. Row order only (same rows, different order; checked by sorting every list) in 12 cases: `bar_graph_sum_by_state_month`, `calc_last_value`, `calc_window`, `dq_reporting_completeness_line_graph`, `group_granularity_{day,quarter,week}`, `line_graph_bump_chart_quarter`, `line_graph_heat_tiles_week`, `line_graph_time_by_state`, `table_disaggregated`, `policy_table_disaggregated`. Order is visible in tables and charts, so INV-2 needs it unchanged.

  Suggested: branch `mig/WP-3b-cpython-313-core` from this branch, list the files under a `core-*` instance here, and keep the fixes to `web/server/query/**`. Other pandas users (`util/analysis`, `util/dataprep`, `web/server/routes/views/*`) import on 3.13 but have no suite; a grep for removed pandas 2 / numpy 2 APIs found only the four sites above.
- [x] **backend (blocks unit 3's runtime claim): `collections` ABC aliases, removed in Python 3.10, raise AttributeError at call time.** No suite covers them, so they pass import and the suites. Start with a failing test (QA-1).
  - `web/server/util/util.py:253-256,373,379,404`: `collections.Mapping`, `collections.Iterable` → `collections.abc.*`;
  - `web/server/potion/managers.py:128`: `collections.Mapping` (Potion update path).
  - Low: `web/server/util/data_catalog.py:205` invalid escape `"\^"` (SyntaxWarning on 3.12+, an error in a later Python); `web/dev_reloader.py:16` still watches `venv_pypy3`.
  - Done on `mig/WP-3b-cpython-313-backend` at `6eca3cc`: all the sites above and both low items. See the 2026-10-05 backend log line and "Backend: `collections` ABC aliases" under Evidence.
- [x] **core (blocks the PR, PERF-7): parse streamed Druid responses fast on 3.13 without losing Long.MIN_VALUE.** Done by core-1, 2026-10-05, `ab662b4`: `db/druid/json_stream.iter_json_array` replaces ijson-bigint and needs no new dependency. It streams the response row by row with the stdlib's C scanner: 200,000 array rows parse in 0.47 s (yajl on 3.9: 0.37 s; the image's pure-Python ijson: 2.98 s) at a 9.6 MB peak on a 200 MB body. Every in-domain value, Long.MIN_VALUE included, equals yajl's. `0cc4efb` used msgspec at first; the lead's review (whole-body decode, resource exhaustion) replaced it. libyajl can stay out of every image; nothing imports ijson now. Evidence: "Core: PERF-7 parser". `db/druid/query_client.py` streams every `GroupByQueryBuilder` response (`streaming = True`) through `ijson.items(fp, 'item', use_float=True)`. Before this WP the web image built `ijson-bigint`'s C backend (`yajl2_c`). That fork's C code does not compile on 3.11+ (`PyGenObject has no member gi_code`), so on 3.13 ijson falls back to its pure-Python backend. `WP-3b-evidence/ijson_probe2.py`, 200,000 rows (19.6 MB): base image `yajl2_c` 0.20 s; this image `python` 3.31 s. The alternatives are wrong: upstream `ijson` 3.5.1's `yajl2_c` (0.14 s) and the `yajl2` ctypes backend over Debian's libyajl2 both fail with `integer overflow` on `-9223372036854775808`, which is the yajl bug the fork exists for. The stdlib `json` parser is fast and exact, but it does not stream. The choice is core's; infra keeps libyajl out of the image so ijson cannot pick the ctypes backend. Hosts with libyajl installed (this build host) get the ctypes backend in `uv sync` environments, so the golden suite here runs on it.
- [ ] **pipeline (non-blocking, after unit 4):** drop `SetupEnvForPyPy` from `util/pipeline/bash/common.sh` and its callers in `pipeline/{harmony_demo,template}/process/run/*`, and the `_pypyjson`/`__pypy__` branches in `data/pipeline/datatypes/base_row.py` and `data/pipeline/io/druid_writer.py`. Without `venv_pypy3` the function prints a warning and keeps the CPython venv, so nothing breaks meanwhile. Also the invalid escapes in `data/pipeline/scripts/fetch_database_tables.py` and `xlsx_to_csv.py`. FYI: `savReaderWriter` left the `pipeline` group; it cannot import on Python 3.10+ (`from collections import Iterable`) and nothing in the repository imports it.
- [ ] **qa (non-blocking):** `tests/pipeline/run.sh` defaults to 3.9 and says 3.12+ cannot import `config/`; `tests/pipeline/requirements.txt` pins `future==0.18.3`, which imports `imp` (gone in 3.12), and README line 29 says the same. On this branch the suite passes on 3.13 from the root lock (130 passed).
- [ ] **lead and human (before this branch merges):** the root `pyproject.toml` now needs uv 0.12.16 or later (hashed build constraints, `required-version`). The build host's `uv` is 0.12.5, and every uv command in a checkout of this branch stops with "Required uv version `>=0.12.16` does not match", including `uv run --no-project` from the repo root. Update uv on the host (`uv self update` to 0.12.23) and tell the other roles. The CI job is renamed "Python 3.13 - lint, types, tests" and the "Python 3.13 - standalone tools" job is gone; if branch protection lists check names, update it.
- [x] **lead / WP-2g core supporter: images built with uv compile bytecode at build time**, so a first start prints no compile-time SyntaxWarnings before logging is configured. The web image sets `UV_COMPILE_BYTECODE=1` for `.venv` and runs `python -m compileall` over the app code it copies (unit 3). The pipeline and dev images follow in units 4 and 5.
- [ ] **human (before deploying this image): the web and worker processes now run as uid 1000 (`zenysis`).** The entrypoint `docker/web/run_as_zenysis.sh` starts as root, hands `/data/output` (the directory and its `*.log*` files), `/data/output/zenysis_static` and `/zenysis/uploads` to uid 1000, and copies `/root/.mc/config.json` into the user's home. Then it drops root with `setpriv`. On a host this changes the owner of `${DATA_PATH}/output` (top level, logs, static files) and `${DATA_PATH}/ubuntu/uploads` to uid 1000, which is `ubuntu` on Ubuntu hosts. Nothing else on the host changes. If a host's uid 1000 is someone else, say so before deploying.
- [ ] **lead (non-blocking):** `scripts/watch/watch_util.py` invalid escape (SyntaxWarning); `.vscode/settings.json` excludes `venv_pypy3`.
- [x] **lead (from core-1, before merging core's work):** Merged `-core-2` at `59dcfcc` (2026-10-06); the empty `-core` branch was ignored. core's commits are on `mig/WP-3b-cpython-313-core-2` (head below), branched at `8dfe8da`. The suggested `mig/WP-3b-cpython-313-core` is checked out in the locked worktree `.claude/worktrees/agent-a870396bbd54f25e2`, which a worktree-isolated agent cannot touch.
- [x] **infra (from core-1, non-blocking):** Done in `2f32b24`; the image rebuilt at `c1fa3e3` installs no JSON stream parser, and the parse runs in it (Evidence, "Merged tree"). `docker/web/Dockerfile_web-server` lines 9-11 explain "No yajl" by ijson's ctypes backend. ijson is gone, so that reason is stale; libyajl is still not needed. Also rebuild the web image once to confirm the PERF-7 claim in it: `db/druid/json_stream.py` is stdlib-only, so nothing new is installed.
- [x] **qa (from core-1, non-blocking; qa-owned, so infra left them):** Done by qa in `35de49f` (2026-10-06) on `mig/WP-3b-cpython-313-qa`; golden 272 passed. `tests/golden/README.md` ("gzip and `ijson` decoding of streamed responses") and the `tests/golden/harness.py` module docstring ("gzip and ijson decoding") name ijson; the client now decodes with `db.druid.json_stream`. Docs only; the suite needs no change (269 passed).

- [x] **qa (blocks the contract replay on this branch, not an infra unit):** Done by qa in `6fe04e5` (2026-10-06) on `mig/WP-3b-cpython-313-qa`; a second blocker found on the way is fixed there too (the stack mounted the checkout over the image's `/zenysis/.venv`). Contract 296 of 296 green on a fresh stack (Log, Evidence). `tests/contract/stack/stack.sh:86` tags the stack image by hashing `requirements.txt` and `requirements-web.txt`, which unit 7 deleted, so `stack.sh up` stops under `set -e` on this branch. Hash `pyproject.toml`, `uv.lock` and `docker/web/Dockerfile_web-server` instead.
- [ ] **core (non-blocking):** `tests/druid/test_druid_response_parsing.py::test_large_response_parses_fast` asserts a wall time under 0.5 s. With the build host at load 45 on 16 cores it measured 0.66 s once and passed on the rerun. Compare against a baseline measured in the same process (for example `json.loads` of the same body), or use CPU time.
- [ ] **core (non-blocking):** pandas 2.2 warns `'m' is deprecated` at `db/druid/query_builder.py:849` (`pd.period_range(..., freq=freq)`), 800 warnings per golden run; pandas 3 removes the alias.
- [x] **infra (WP-4a QA low, routed by the lead): `typing_extensions` 4.13.2 for the 3.8 lane.** Superseded here: no lane or image runs 3.8 after this WP, and neither 3.13 image installs cryptography, whose 3.8 requirement caused the `pip check` conflict. `uv pip check` passes in the locked environment (`test_the_locked_environment_satisfies_every_installed_requirement`) and in both images. `typing_extensions` stays at 4.12.2, pydantic 2.10's floor.
- [x] **infra (WP-4a QA low, routed by the lead): the PyPy wheel through a bind mount, not `COPY`.** Superseded here: the `rust` and `pypy-wheels` stages, the `--find-links` install and the drift test are deleted with PyPy (unit 4 and unit 10). `tests/infra/test_one_interpreter.py` fails if a Dockerfile installs PyPy.
- [ ] **lead: the 3.8 guard's directory list** (decision: the guard checks everything the 3.8 image can import). This WP deletes the guard with the 3.8 image (unit 8), so the list matters only on `mig/integration` until this WP merges. Side branch `mig/WP-3b-py38-guard` at `60f78e1`, from integration `290cd65`: the step also checks `harmony tests/authz tests/privilege_escalation tests/db tests/contract tests/infra tests/core`, and `tests/infra/test_py38_guard.py` fails when a web image copies a Python file outside the guarded directories (2 failed before, 3 passed after). When this WP merges after it, keep this WP's side of `integration.yml` and delete that test.
- [ ] **infra, at WP-1h's merge (deferred): the renderer's restart policy outside prod** (WP-1h request: `restart: unless-stopped` in `docker-compose.yaml`; the renderer exits with status 70 when a slot is stuck).
- [ ] **infra, at WP-1h's merge (deferred): type-check `harmony/worker` against Playwright's real types** (WP-1h reviewer finding 5). WP-1h's suggestion targets `ci/tools313`, which this WP deletes. On 3.13: add `playwright==1.63.0` (the Python package only) to a dependency group that CI's mypy step installs, and drop `playwright.*` from the missing-import overrides.
- [ ] **infra with qa, WP-2f follow-up (deferred): the end-to-end (Playwright) CI job.**

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
- 2026-10-05 infra-3: status review. Every infra unit is done and the three images build at the head. The pull request still waits on core's two blocking requests: golden on pandas 2 (unit 1b) and the ijson parse speed (PERF-7). It also waits on backend's `collections` fix, the lead's uv update, and the qa and reviewer verdicts. `task_gate.py WP-3b`: status and the two verdicts outstanding.
- 2026-10-05 core-1 (supporting): branch `mig/WP-3b-cpython-313-core-2` at `8dfe8da` (the `-core` branch is held by a locked worktree; Requests). uv through `uvx --from uv==0.12.23 uv ...`, because the host's uv 0.12.5 fails `required-version`.
- 2026-10-05 core-1 unit 1b: golden on pandas 2.2 (`d9382b0`). Five causes fixed in shaping, none in a fixture: outer-merge order in `export_pandas` date filling, positional `drop` axis, `Series.iteritems`, strict `to_datetime` format, `to_dict(into=...)`. Check: golden 269 passed; 6 unit tests, each red on `8dfe8da` for its cause; 3300 synthesised variants identical to pandas 1.5.3 on 3.9; ruff, lint gate, mypy 518 files.
- 2026-10-05 core-1 PERF-7: `0cc4efb` moved parsing to msgspec (whole-body decode). The lead routed a security review finding (resource exhaustion), and `ab662b4` replaced it with a stdlib streaming decoder, `db/druid/json_stream.py`, with no new dependency. Check: `tests/druid` 222 passed (198 golden round trips, edge values, read boundaries, bounded memory, red on `0cc4efb` at 65.9 and 128.1 MiB); golden 269; every suite passes (core 25, druid 222, druid_setup 79, golden 269, graphql 22, infra 164, pipeline 130, toolchain 12, web 99); `uv lock --check`; lint gate; mypy 519 files.
- 2026-10-05 backend (WP-3b support), the `collections` request: `web/server/util/util.py` (`deep_update`, `assert_iterable`, `assert_non_string_iterable`, and `assert_mapping`, which `PythonModel.deserialize` calls) and `web/server/potion/managers.py` (`AuthorizationResourceManager.update`, the dashboard and alert PATCH path) now use `collections.abc`. The `data_catalog.py` escape and the `dev_reloader.py` `venv_pypy3` entry are fixed. Check: `tests/web/test_collections_abc_call_paths.py` failed 4 of 4 with `AttributeError: module 'collections' has no attribute ...` before the change and passes after; `tests/web` 99 passed (95 plus 4); ruff check and format on the changed files pass, as does the E9/F63/F7/F82 gate on the whole tree; mypy is clean on 518 files; `compileall -W error::SyntaxWarning` over `web graphql models` is clean; the image import sweep is identical to `u3` and to infra-3's recorded TSV (689 OK / 64 ERR); the call probe gives ERR in `u3` and OK at `6eca3cc` (Evidence). Tooling: the host has uv 0.12.5, so every uv command ran as `uvx --from uv==0.12.23 uv ...`. A dead agent's locked worktree still held the branch, so the branch was switched in with `--ignore-other-worktrees`.

- 2026-10-06 infra-3 resumed after a lost builder: the branch switched into a new worktree at `8dfe8da`. The host's uv is 0.12.5, so every uv command ran as `uvx --from uv==0.12.23 uv ...`, through a shim first on `PATH` for scripts that call `uv` (`ci/pytest_suites.sh`, `ci/lint_python.sh`). Docker builds used `--network host`, and runs that fetch used `--dns 1.1.1.1`.
- 2026-10-06 infra-3 unit 9: merged `-core-2` (`59dcfcc`), backend (`512c6ba`; conflict in this file, both sides kept), `mig/integration` `7c34bca` (`421f56b`) and `290cd65` (`c1fa3e3`, clean). Conflicts in `421f56b`: `requirements*.txt` stay deleted, and their WP-4a pins live in `pyproject.toml`. `pyproject.toml` takes future 1.0.0 with pydantic 2.10.6 and pydantic-settings 2.8.1, `typing_extensions` 4.12.2 without PyPy markers, and mypy over `harmony/core` and the browser share tool with both plugins. `uv.lock` was re-locked, keeping integration's annotated-types 0.7.0, grimp 3.13 and python-dotenv 1.2.1. The pipeline Dockerfile keeps the 3.13 image and integration's `COPY harmony`. The worker keeps `--schedule` and drops `--loglevel` (WP-2g). Agent memory takes the union. Check at `c1fa3e3`: all 14 suites pass (counts under Evidence); golden `record.py --check` gives 86 cases, 0 drift; `uv lock --check`; lint gate; mypy 521 files; import-linter 1 kept; `flask db upgrade` and `current` print `2b730c14f514 (head)`.
- 2026-10-06 infra-3 unit 10 (`2f32b24`): `compileall` covers `harmony`; the PyPy drift test and the "No yajl" note go. Check: the new test fails with `{'harmony'}` before and passes after; `tests/infra` 448; `docker build --check` clean.
- 2026-10-06 infra-3 unit 11 (`373935c`): job `python-stack`. Check: `tests/infra/test_ci_stack_job.py` 1 failed before, 4 passed after; `ci/pytest_suites.sh -m stack` locally: all 14 suites pass (contract 234 skipped without `CONTRACT_BASE_URL`, the rest select nothing); WP-0k's tree (`1b442f7`) with the same selection: 12 passed, 481 deselected, the clock test at three time zones; actionlint, zizmor (12 suppressed, as before) and the policy are clean.
- 2026-10-06 infra-3 unit 12 (`9c6ae53`): `dataclasses` removed. Check: the pip-check test fails on `dataclasses requires Python >=3.6, <3.7` before and passes after; `uv pip check` is clean in both `d2` images.
- 2026-10-06 infra-3: images rebuilt from `c1fa3e3` as `local/wp3b-infra3d/harmony-{web-server,web,etl-pipeline}:d2`, next to `:int` images built from `mig/integration` `7c34bca` (CPython 3.8 web, PyPy and 3.9 pipeline). The import sweeps, the call probe, the pipeline suite in the image, the stack probe and the PERF-7 parse in the image are under Evidence.
- 2026-10-06 infra-3: side branch `mig/WP-3b-py38-guard` (`60f78e1`) for the lead (Requests).
- 2026-10-06 infra-3: status stays review. `task_gate.py WP-3b`: status, and the qa, reviewer and security verdicts outstanding.
- 2026-10-06 infra-3: merged qa's `mig/WP-3b-cpython-313-qa` `6e110a6` (`45291b6`, no conflicts): the contract stack tags its image from the Dockerfile, `pyproject.toml` and `uv.lock` and mounts the checkout at `/src`; the golden docs name `db.druid.json_stream`. Check: all 14 suites pass (contract 71 with 234 `stack` deselected, the rest as under "Merged tree"); `uv lock --check`, lint gate, mypy 521 files, import-linter 1 kept. `task_gate.py WP-3b`: status and the three verdicts outstanding.
- 2026-10-06 qa (supporting, `mig/WP-3b-cpython-313-qa` from `c552702`): the two qa requests. `6fe04e5`: `stack.sh` tags the web image by `docker/web/Dockerfile_web-server`, `pyproject.toml` and `uv.lock` (new `stack.sh image-tag`), and the stack mounts the checkout read-only at `/src`, because a mount at `/zenysis` hid the image's `/zenysis/.venv` (`web-init` exited 127, `/zenysis/.venv/bin/flask: cannot execute`). `35de49f`: golden README and harness docstring name `db.druid.json_stream`. Check: `tests/contract/test_stack_image_tag.py` 5 failed (`cat: .../requirements.txt: No such file`) before and 9 passed after; full contract replay on one fresh stack built from `c552702` plus these commits, web on CPython 3.13.16 from the image venv: 305 passed (234 replay, 62 offline, 9 new), so the 296 existing cases are all green and no case differs (WP-3b changes no contract); authz live layer on a second fresh stack: 583 passed; golden 272, contract offline 71, infra and toolchain 465; ruff clean.

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

### Backend: `collections` ABC aliases

- **Sites.** A grep over first-party code for every alias that Python 3.10 removed (`collections.<ABC>` and `from collections import <ABC>`) finds only `web/server/util/util.py` and `web/server/potion/managers.py`. No first-party code monkey-patches `collections`. In the 3.13 venv, `flask_potion`, `flask_principal`, `flask_user` and `flask_login` do not use the aliases. The call-time paths are `deep_update`, `assert_iterable`, `assert_non_string_iterable`, `assert_mapping` (which `models/python/base.py` `PythonModel.deserialize` calls) and `AuthorizationResourceManager.update`. `DashboardManager` (`web/server/routes/views/dashboard.py`) and `AlertDefinitionManager` (`web/server/database/alerts.py`) inherit that `update`.
- **Test first.** On 3.13 at `8dfe8da`, `tests/web/test_collections_abc_call_paths.py` gives 4 failed, with `AttributeError` at `util.py:253`, `:373` and `:404`, and at `managers.py:128`. At `6eca3cc` it gives 4 passed, and `tests/web` gives 99 passed.
- **Image.** `docker build -f docker/web/Dockerfile_web-server -t local/wp3b-backend/harmony-web-server:6eca3cc .`, then `Dockerfile_web` over that image with `NAMESPACE=local/wp3b-backend TAG=6eca3cc`. The client image is re-tagged from `local/wp3b-infra3/harmony-web-client:u3`, because the client did not change. `sweep_image.sh local/wp3b-backend/harmony-web:6eca3cc` gives 689 OK / 64 ERR. The `diff` is empty against `local/wp3b-infra3/harmony-web:u3` and against infra-3's `sweep_web_u3.tsv`. The `-server` image alone gives 686 / 67. Its 3 extra errors are `No module named 'scripts'`, because only the full image copies `scripts`.
- **Call probe** (`WP-3b-evidence/backend/call_probe.sh <image>`, uid 1000, no network). In `local/wp3b-infra3/harmony-web:u3`, all four calls print `ERR AttributeError: module 'collections' has no attribute 'Mapping'` (`'Iterable'` for `assert_iterable`). In `local/wp3b-backend/harmony-web:6eca3cc`, all four print `OK`.

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

### Core: pandas 2 shaping (unit 1b, `d9382b0`)

Scripts are in `WP-3b-evidence/core/`. The pre-WP reference is a `git archive 15bdde3` tree synced from its own lock: CPython 3.9.25, pandas 1.5.3, numpy 1.21.0, ijson-bigint `yajl2_c`. Its golden suite passes 269, and its shaping code is identical to `8dfe8da`.

- **Causes**, one per class the lead listed, with each fixture as the oracle:

  | Class | Cause | Cases | Fix |
  |---|---|---|---|
  | groupby / merge ordering | pandas 2.2 sets `sort = sort or how == "outer"` in `_MergeOperation`, so `export_pandas`'s date-filling `merge(how='outer', sort=False)` came back sorted by key. pandas 1.5 numbered keys by first appearance (left, then right) and emitted key by key. | the 12 row-order cases | `query_builder.outer_merge_in_appearance_order` restores that order. |
  | datetime handling | pandas 1.5 ignored `format='%Y-%m-%d'` for ISO strings and parsed `2024-01-01T00:00:00.000Z` as UTC; pandas 2 applies the format strictly. | `dq_data_quality`, `policy_dq_data_quality` | `parse_druid_timestamps`: `format='ISO8601'`, the same `datetime64[ns, UTC]` values and NaT. |
  | dtype / boxing | `to_dict('records', into)` no longer builds rows through `into`, and it writes boxed values back by column name. | `map_by_municipality`, `policy_map` | `[data_point(row) for row in df.to_dict('records')]`; values stay native `int`/`float`. |
  | removed API | `DataFrame.drop('index', 'columns')`; `Series.iteritems()` | `hierarchy_*`, `policy_hierarchy`, `dq_outliers_box_plot`, `policy_dq_outliers_box_plot` | `drop(columns='index')`; `.items()` |
  | NaN vs None, string vs object | no difference: pandas 2.2 keeps object strings and the same NaN handling (`fillna(np.nan)` still downcasts, with a FutureWarning) | none | none |

- **Golden:** 269 passed, `git diff 8dfe8da -- tests/golden` empty.
- **Unit tests**, each pinning the pandas 1.5.3 output of the pre-WP code (`capture.py` printed it in the base tree): `tests/druid/test_export_pandas_order.py` (2) and `tests/web/server/query/test_pandas2_shaping.py` (4). On `8dfe8da` with the 3.13 lock, each fails for its cause: order mismatch, `KeyError: 'MunicipalityName'`, `TypeError: DataFrame.drop() takes from 1 to 2 positional arguments`, `AttributeError: 'Series' object has no attribute 'iteritems'`, and an import error for the extracted `parse_druid_timestamps`.
- **Beyond the recordings** (`fuzz.py`): every case replayed against fresh synthesised Druid answers, 20 seeds, plus 20 with NaN, ±Infinity and null forced in, is 3300 variants. Body digests on 3.13 / pandas 2.2 equal those on 3.9 / pandas 1.5.3 in all 3300, with no errors on either side. Reverting only the merge fix makes 134 of 825 variants (5 seeds) differ, so the check has teeth.
- **The merge helper alone** (`merge_diff.py`): 417 random non-empty frame pairs, with duplicate and null keys on both sides, left-only and right-only keys, and int, float and bool columns. The helper on pandas 2.2 against `merge(how='outer', sort=False)` on pandas 1.5.3 gives identical columns, dtypes, index and rows in every pair. With an empty side pandas 1.5 took another path; `export_pandas` returns before merging an empty frame, and its right side is never empty.
- **Cost:** 144k rows date-filled to 240k: 136 ms, against 45 ms for pandas 1.5's merge (pandas 2.2's own sorted merge alone is 75 ms).
- **Left for pandas 3** (FutureWarnings, the same results on 2.2): `visualizations/base.py:106` object downcasting in `fillna`; `query_builder.py` `period_range(freq='m'|'w'|'q')` lowercase aliases.

### Core: PERF-7 parser (`0cc4efb`, then `ab662b4`)

The final timings were taken in one run (`final_measure.sh`, output in `final_measure.txt`; it expects the base tree at `/tmp/core3b/base` and the bodies from `parse_bench.py make` and `make_200mb.py`) on the shared build host, load average 13 to 17, with old and new measured back to back. Earlier runs on a quieter host gave the same numbers within 5%. "Old" is the base tree with ijson-bigint `yajl2_c` on CPython 3.9.25, the backend the 3.8 image used (no 3.8 interpreter is on the host).

- **Design.** `db/druid/json_stream.iter_json_array(fp)` yields the elements of the top-level array. It decodes one element at a time with the stdlib's C decoder (`JSONDecoder.raw_decode`) from a rolling buffer fed by an incremental UTF-8 decoder over the gzip stream, and drops consumed text. No new dependency; ijson-bigint goes from `pyproject.toml` and `uv.lock`, and nothing imports ijson. Both streamed call sites (`DruidQueryClient_.run_raw_query` and `DruidQueryClient.run_raw_query`) return the iterator, as `ijson.items` did.
- **Review finding (lead, 2026-10-05: resource exhaustion in `0cc4efb`).**
  1. *Streaming.* `0cc4efb` decoded the whole body with msgspec. `ab662b4` streams again, so there is no whole-body step and no byte cap; a cap would only have made large queries fail that work today. A gzip bomb streams too: 64 MiB of whitespace stays under 8 MiB traced (`test_highly_compressed_body_streams_without_inflating`; 128.1 MiB on `0cc4efb`).
  2. *Peak memory* (`memory_bench.py` under `/usr/bin/time -v`; growth over the post-import baseline; `stream` drops each row, `retain` keeps every row, as `export_pandas` eventually holds them all in its frame):

     | Body | Consumer | Old (yajl stream) | `0cc4efb` (msgspec) | `ab662b4` (stream) |
     |---|---|---|---|---|
     | largest golden (`dq_data_quality`, 294 rows, 10 KB) | stream / retain | +0.0 / +0.0 MB (process 36.8 / 35.9 MB) | +0.0 / +0.0 MB | +0.0 / +0.0 MB (process 36.3 / 36.4 MB) |
     | synthetic 200 MB (1,013,631 rows, 68 MB gzip) | stream | +0.6 MB, 1.89 s | +902.6 MB, 1.37 s | +9.6 MB, 2.48 s |
     | synthetic 200 MB | retain | +705.9 MB, 2.96 s | +902.5 MB, 1.42 s | +670.8 MB, 3.12 s |

  3. *Laziness.* Only `GroupByQueryBuilder` sets `streaming = True`. Its two call sites pass the result straight to `GroupByQueryBuilder.parse`, a generator, so `pydruid_query.result` stays a generator, and `export_pandas` still builds the frame in 100,000-row chunks. `static_data_query_client` already calls `list(...)`. Nothing catches parser errors or `DruidQueryError` around these calls. As with ijson, a malformed body raises (`ValueError`) during iteration.
- **Parse speed** (`parse_bench.py`; gzip body; best of 5; peak growth):

  | Parser | 200,000 array rows (36 MB) | 200,000 object rows (19.6 MB, infra's shape) |
  |---|---|---|
  | old: ijson-bigint `yajl2_c`, 3.9 | 0.366 s, streaming | 0.156 s |
  | the 3.13 image before this: ijson pure Python | 2.984 s | 2.048 s |
  | ijson `yajl2` ctypes (host libyajl) | `integer overflow` on Long.MIN_VALUE | |
  | **`json_stream` (this branch)** | **0.468 s, +0 MB** | **0.185 s, +0 MB** |
  | stdlib `json.load`, whole body | 0.435 s, +188 MB | 0.156 s, +104 MB |
  | orjson 3.12.0, whole body | 0.287 s, +238 MB | 0.142 s, +173 MB |
  | msgspec 0.21.1, whole body | 0.274 s, +163 MB | 0.120 s, +121 MB |

- **End to end** (`e2e_bench.py`: `/api2/query/table` for `table_disaggregated`, its recorded response scaled with a unique municipality per copy, through the production client, `parse`, `export_pandas` and shaping; best of 3; the fake broker's own `json.dumps` and gzip subtracted):

  | Rows | Old | 3.13 image before this (pure-Python ijson) | This branch |
  |---|---|---|---|
  | 200,000 | 2.21 s, 258 MB | 3.22 s, 230 MB | 1.95 s, 228 MB |
  | 600,000 | 6.97 s, 670 MB | 10.27 s, 616 MB | 6.84 s, 616 MB |

- **Values** (`edge_parse.py`; `edge_yajl2_c_py39.tsv` against `edge_py313.tsv`). On every document Druid sends, `json_stream` equals yajl in value and type: int64 extremes including Long.MIN_VALUE, `-0.0`, subnormals, max double, 17-digit rounding, quoted NaN and infinities, null and booleans, raw and escaped non-ASCII including surrogate pairs, and nested arrays and objects. It rejects, with `ValueError`, everything yajl rejected: bare NaN and Infinity, `1e309`, truncated bodies, invalid UTF-8. It differs only outside Druid's range, exactly as the 3.13 image's pure-Python ijson already does: integers beyond 64 bits stay exact where yajl refused them, and a lone `\ud800` escape stays as-is where yajl gave `?`. Rejected alternatives on the same inputs: orjson turns integers beyond 64 bits into lossy floats; whole-body `json` accepts bare NaN and `1e309` (as inf).
- **Tests** (`tests/druid/test_druid_response_parsing.py`, 218 with parameters): 198 golden round trips (each `druid_response.json` entry, ASCII-escaped and raw UTF-8, through the real client, compared by type and value with the stdlib); edge values; bodies yajl rejected; every read boundary from 1 to 7 bytes over the golden and edge bodies; array framing; identity encoding; a 100,000-row body under 0.5 s (pure-Python ijson: 1.28 s, red); bounded memory for a 12 MB body and a highly compressed one (red on `0cc4efb` at 65.9 and 128.1 MiB). Golden: 269 passed.

### Merged tree (infra-3, 2026-10-06, head `c1fa3e3` plus this file)

Scripts are under `WP-3b-evidence/`. Images are `local/wp3b-infra3d/*:d2` (this branch) and `:int` (`mig/integration` `7c34bca`). The web client image is shared, because `web/client`, `package.json`, `yarn.lock` and `Dockerfile_web-client` match `8dfe8da` and integration.

- **Suites** (`ci/pytest_suites.sh`, `CI=true`, CPython 3.13): alerts 9, authz 4681 (583 skipped), contract 62 (234 `stack` deselected), core 185, db 26, druid 240 (11 skipped), druid_setup 83, golden 272, graphql 22, infra 453, pipeline 130, privilege_escalation 86, toolchain 12, web 291 (1 xfailed). All pass. In one run, druid's wall-clock test measured 0.66 s against its 0.5 s bound with the host at load 45; the rerun passed (core request).
- **Golden:** `record.py --check`: 86 cases, 0 fixture files would change.
- **Lint and types:** `uv lock --check` exit 0; `ci/lint_python.sh mig/integration` exit 0; mypy "no issues found in 521 source files"; `lint-imports` 1 kept, 0 broken. There is one Python lane, 3.13; `ci/check_py38_syntax.py` was deleted in unit 8 and runs only on the side branch (938 files, 0 problems on CPython 3.8.20).
- **Workflows:** actionlint 1.7.12 with shellcheck 0.11.0 exit 0; zizmor 1.30.1 `--offline` no findings (12 suppressed); `workflow_policy.py` "policy OK (3 workflows)".
- **Compose and Dockerfiles:** `compose_config.sh` OK for all 9 file sets. `docker build --check` reports no warnings for web-server, web (with the local namespace and tag; the default `ghcr.io` tag is not published), pipeline and dev. The client Dockerfile's 3 `LegacyKeyValueFormat` warnings predate this WP; the file is unchanged from integration.
- **Web image** (`d2`, 947 MB; `int` 2.45 GB): Python 3.13.16, uid 1000 `zenysis`, no gcc, git, uv or libyajl, 4 `.pyc` files under `harmony/`. No JSON stream parser is installed: none of `ijson`, `msgspec`, `orjson` or `yajl` is importable, and `pyproject.toml`, `uv.lock` and `docker/` do not mention them. `uv pip check`: 116 packages compatible.
- **Web import sweep** (`sweep_image.sh`, now including `harmony`): `d2` as uid 1000 698 OK / 62 ERR; `int` (CPython 3.8.20, root) 697 OK / 62 ERR. The only difference is `db.druid.json_stream OK`, core's new module. The errors are the same modules with the same messages.
- **Call probe** (`backend/call_probe.sh`): `deep_update`, `assert_iterable`, `assert_mapping` and `AuthorizationResourceManager.update` all OK in `d2`.
- **Runtime** (`web_stack/run.sh` with `NS=local/wp3b-infra3d TAG=d2`; base, local and prod files plus the overlay): web and worker are healthy. Every web process runs as `zenysis`, including PID 1 after `run_as_zenysis`; the 18 celery processes run as `zenysis`. `create_user.py` works through the entrypoint. HTTP from inside web: `/` 200, `/login` 200, anonymous `/api2/user` 401, `/static/build/version.txt` 404, login 200, `/api2/user` 200 (1), `/api2/role` 200 (20), `/overview` 200, `/data-catalog` 200, the same as `u3`. Ownership after the upgrade-from-root simulation: logs, static files (stale file replaced), uploads and the mc config are uid 1000. The beat schedule is at `/tmp/celerybeat-schedule`. Every web and worker log line is JSON (WP-2g); the only ERROR is the static 404.
- **Pipeline image** (`d2`, about 1.4 GB; `int` 4.06 GB): CPython 3.13.16; no `pypy3`, `python3.9`, gcc, rustc, cargo, `venv_pypy3` or wheel directory. `uv pip check`: 124 packages compatible. `pipeline/pipeline_in_image.sh` (with `DOCKER_RUN_EXTRA=--dns 1.1.1.1`): 130 passed. `sweep_pipeline.sh` (now including `harmony`): `d2` 770 OK / 77 ERR; `int` (its CPython 3.9 venv) 769 OK / 77 ERR. The differences are `db.druid.json_stream OK`, and three WP-8a audit scripts under `scripts/druid/null_audit/`, which fail in both images: on `int` for lack of `flask_testing`, on `d2` one import later for lack of `tests/`. These are dev-only harnesses that no image runs.
- **PERF-7 in the image** (`perf7_in_image.sh`: core's `parse_bench.py`, 200,000 rows, best of 5, uid 1000, no network). Three rounds with the host at load 40 to 46 on 16 cores. Array rows: `int`'s yajl2_c 0.73 to 0.97 s, `d2`'s `json_stream` 1.83 to 1.86 s. Dict rows: 0.33 s and 0.50 to 0.79 s. Peak RSS growth stays at 7 MB or less for both. The same run interleaved with the branch's host environment gave host 1.38 to 1.95 s and image 1.28 to 1.29 s, so the image adds no cost; the load inflates every number (core measured 0.47 s on a quiet host). The PERF-7 verdict belongs to decision 0011's paired A/B gate on a quiet host.
- **`flask db`** (`flask_db_check.sh` on the branch environment): `upgrade` exit 0, `alembic_version` `2b730c14f514`; `current` exit 0, `2b730c14f514 (head)`.
- **CI stack job:** the selection over WP-0k's tree is `pytest -m 'not stack' -m stack tests/web`, which is what `ci/pytest_suites.sh -m stack` runs per suite. It gave 12 passed, 481 deselected, against a throwaway `postgres@sha256:f7d2…`. `tests/infra/test_ci_stack_job.py` also pins that the last `-m` wins and that the contract replay skips without the compose stack.

### QA: contract stack on the 3.13 image (qa, 2026-10-06, `6fe04e5`)

- **Red before:** `uv run pytest tests/contract/test_stack_image_tag.py` on `c552702` plus the `image-tag` extraction: 5 failed, every one on `cat: <root>/requirements.txt: No such file or directory`. After `6fe04e5`: 9 passed. The test reads the hash inputs from the Dockerfile's `--mount=type=bind,source=` lines, so a new bind mount that the tag does not hash fails it.
- **Stack:** `CONTRACT_PROJECT=qa-3b-contract CONTRACT_WEB_PORT=58761 stack.sh up`, with an untracked copy that only added `--network host` to `docker build` (host egress; deleted after). Image `harmony-contract-web-server:ea60c24c18a8`. In `web`: Python 3.13.16, `sys.executable` `/zenysis/.venv/bin/python`, Flask 1.0.4, `web.server.app` loaded from `/src`. Hasura metadata applied.
- **Replay:** `eval "$(stack.sh env)"; uv run pytest tests/contract -q -p no:randomly`: 305 passed in 17.45 s (`test_replay` 234, `test_cases` 26, `test_catalogue` 14, `test_schema` 22, `test_stack_image_tag` 9). Log `/tmp/wp3bqa_replay.log`.
- **Authz live layer:** `CONTRACT_PROJECT=qa-3b-authz CONTRACT_WEB_PORT=58762 CONTRACT_USERNAME=authz-admin@harmony.invalid`, same image; `uv run --locked pytest tests/authz -q -p no:cacheprovider -W ignore -m authz_http`: 583 passed, 4681 deselected in 327 s. Log `/tmp/wp3bqa_authz_http.log`.
- **Cleanup:** both stacks `down` (containers, networks, tmpfs and secrets gone), the image removed by tag.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | root-start entrypoint (`docker/web/run_as_zenysis.sh`) |
