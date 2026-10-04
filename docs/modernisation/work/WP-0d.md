---
wp: "0d"
title: "Delete dead backend code and dependencies"
status: review
owner_role: "core"
instances:
  - name: "core-2"
    branch: "mig/WP-0d-dead-backend-code"
    files:
      - docs/modernisation/work/WP-0d.md
      - docs/modernisation/work/WP-0d-evidence/import_sweep.py
      - docs/modernisation/work/WP-0d-evidence/route_map.py
      - docs/modernisation/work/WP-0d-evidence/pipeline-harness-only.diff
      - docs/modernisation/work/WP-0d-evidence/wp0d_dead.sh
      - docs/modernisation/work/WP-0d-evidence/wp0d_dead.out
      - docs/modernisation/work/WP-0d-evidence/sweep-web-summary.txt
      - docs/modernisation/work/WP-0d-evidence/routes-summary.txt
      - docs/modernisation/work/WP-0d-evidence/sweep-pipeline-trim-summary.txt
      - .claude/agent-memory/harmony-core-engineer/**
  - name: "backend-5"
    branch: "mig/WP-0d-dead-backend-code-backend"
    files:
      - web/server/app.py
      - web/server/routes/graphql_api.py
      - web/server/graphql/**
      - scripts/db/graphql/**
      - graphql/v2/**
      - package.json
      - tests/web/conftest.py
      - tests/web/test_graphql_endpoint_removed.py
      - .claude/agent-memory/harmony-backend-engineer/**
  - name: "infra-5"
    branch: "mig/WP-0d-dead-backend-code-infra"
    files:
      - requirements.txt
      - requirements-web.txt
      - requirements-pipeline.txt
      - requirements-dev.txt
      - mypy.ini
      - log/config.py
      - docs/modernisation/work/WP-0d-evidence/infra5*
      - docs/modernisation/work/WP-0d-evidence/sweep-*infra5*
      - .claude/agent-memory/harmony-infra-engineer/**
  - name: "data-platform-2"
    branch: "mig/WP-0d-dead-backend-code-druid"
    files:
      - db/druid/indexing/legacy_task_builder.py
      - db/druid/indexing/scripts/run_indexing.py
      - db/druid/indexing/resources/**
      - tests/druid/test_hadoop_ingestion_removed.py
      - docs/modernisation/work/WP-0d-evidence/dp2_*
      - .claude/agent-memory/harmony-data-platform-engineer/**
  - name: "frontend-platform-2"
    branch: "mig/WP-0d-dead-backend-code-frontend"
    files:
      - web/client/util/graphql/zen_environment.js
      - web/client/util/graphql/index.jsx
      - .claude/agent-memory/harmony-frontend-platform-engineer/**
branch: "mig/WP-0d-dead-backend-code"
requirements: []
contracts_consumed: []
contracts_changed: []
security_review: false
---

# WP-0d: Delete dead backend code and dependencies

Phase detail: [phase-0-security-and-subtraction.md, section 0d](../phase-0-security-and-subtraction.md).

## Ownership finding

Every path the phase file lists for 0d is owned by another role (`uv run python scripts/agents/ownership.py who ...`):

| Path | Owner |
|---|---|
| `requirements.txt`, `requirements-web.txt`, `requirements-pipeline.txt`, `requirements-dev.txt`, `mypy.ini`, `log/config.py` | infra |
| `web/server/routes/graphql_api.py`, `web/server/graphql/**`, `web/server/app.py`, `web/server/routes/api.py` | backend |
| `db/druid/indexing/resources/**`, `db/druid/indexing/legacy_task_builder.py`, `db/druid/indexing/scripts/run_indexing.py` | data-platform |
| `web/client/util/graphql/**` | frontend-platform |

No core-owned file (`config/`, `data/query/`, `db/` outside `db/druid/indexing/`, `models/`, `util/`, `web/server/{query,data,migrations}`) imports a removed package. Core's part of this WP is therefore to prove each deletion is dead, write the exact change for each owner, and verify the combined change builds and imports.

## Plan

1. Claim; record ownership. Check: ownership tool output above.
2. Prove each target is dead (grep for imports, string references, route callers). Check: grep transcripts under Evidence.
3. Write exact change requests per owning role. Check: each request lists files, lines and blocking unit.
4. Verify the combined change in a throwaway copy that is never committed. The web-server and pipeline images must build with the trimmed requirements. An import sweep over every backend module must give the same result as on the baseline image, apart from the deleted modules. Check: build and sweep output under Evidence.

## Phase-file corrections

- **`/api/timeout` is live, so it is not deleted.** Phase 0d calls it unused, which is wrong.
  - `web/client/util/timeoutSession.js:42` calls `ZenClient.post('timeout', {})`. `ZenClient.post` prefixes `/api/` (`web/client/util/ZenClient.js:18`).
  - `monitorSessionTimeout()` runs from every entry point through `web/client/entryPoints/baseEntry.js`.
  - The handler `ApiRouter.timeout_user_session` (`web/server/routes/api.py:131`) is the server half of automatic sign-out. When `AUTOMATIC_SIGN_OUT_KEY` is on and the session is not remembered, it logs the user out. Deleting it would quietly disable a security control.
  - The lead confirmed this on 2026-10-04. WP-0c is fixing the route's `is_session_persisted` helper. The phase file needs an edit (lead-owned): see the Requests section.
- **The Hadoop templates cannot be deleted on their own.** `db/druid/indexing/legacy_task_builder.py:17-22,64-66` reads `task_templates/index_hadoop.json.tmpl` and `tuning_configs/on_prem.json` into class attributes at import time. Its only importer is `db/druid/indexing/scripts/run_indexing.py`, and nothing imports or runs that script. All four go together.
- **`zen_environment.js` is deleted, not repointed.** Its only consumer is the re-export in `web/client/util/graphql/index.jsx`, and nothing imports `zenEnvironment`. Hasura already has its own environment (`util/graphql/environment.js`, which posts to `/api/graphql`).

## Branch note

At the lead's instruction on 2026-10-04, this branch merges `mig/decisions-0001-ownership` (merge commit `35e9d62`). The diff against `main` therefore includes that branch's `docs/modernisation/SPEC.md` and `docs/modernisation/decisions/0001-*.md` changes. They are not WP-0d edits, and they drop out once the decision branch lands on `main`. Since unit 5 merged `mig/integration`, `task_gate.py WP-0d` reports no file outside the five contributing roles. It lists only the pending status and verdicts.

## Merge order

- This branch already contains the four side branches. The integrated head therefore lands as one unit, which satisfies the backend-before-infra order. Merged on 2026-10-04 in this order:
  1. backend `1e7cfa7`
  2. infra `c310537`
  3. data-platform `2ccbe74`
  4. frontend-platform `ae5d798`
  5. `mig/integration`
  6. After review: backend `d0c8f78` (`/graphql` tool chain), then infra `318cd18`, which fast-forwards (gspread PyPy marker, cryptography pin dropped, `[mypy-graphql_relay.*]` removed), then `mig/integration` again (2026-10-05). `git ls-files .playwright-mcp` is empty.
- The infra trim must never land without the backend deletion. Without it, `_register_routes` fails with `No module named 'flask_graphql'`.
- The `etl-pipeline` image builds only once WP-0b's MinIO fix (`mig/WP-0b-ports-secrets-pins`) is merged. Until then, it stops at the `mc` download with HTTP 410, the same as on `main`. With WP-0b's Dockerfile, infra-5 built it with exit 0. The PyPy step skips `gspread`, so it installs no `cryptography` at all. Merge WP-0b before, or together with, WP-0d.
- **Hand-off to WP-2f (`mig/WP-2f-uv-ruff-mypy-ci`, checked at `c671637`).** Rechecked on 2026-10-05 against the branch head `6ae5d9e`. Between them, `pyproject.toml` changes in no line this hand-off names: the removed packages, the five mypy overrides, the `gspread` line, the `requirements` target, and `mypy.ini` being absent.
  - WP-2f makes `pyproject.toml` the source of `requirements*.txt` (`make requirements` runs `uv run docker/export_requirements.py`), and it deletes `mypy.ini`. A trial merge of the two branches conflicts in all four `requirements*.txt` and in `mypy.ini`.
  - Whichever of WP-0d and WP-2f lands second must, in that WP:
    1. Remove the WP-0d packages from WP-2f's `pyproject.toml`:
       - `[project].dependencies`: `python-Levenshtein==0.12.1` and `google-cloud-logging==1.11.0 ; …`.
       - `web` group: `Flask-Admin`, `graphene-sqlalchemy`, `Flask-GraphQL` and `segment-analytics-python`.
       - `pipeline` group: `fuzzywuzzy`, `jellyfish`, `editdistance` and `dask`.
       - `dev` group: the Paramiko block `cryptography==37.0.2`, `pyasn1==0.4.8`, `PyNaCl==1.4.0` and `paramiko==2.7.1`, with its comment.
    2. Remove the mypy overrides for the removed packages from `[[tool.mypy.overrides]]`: `flask_admin.*`, `flask_graphql.*`, `graphene.*`, `graphene_sqlalchemy.*` and `graphql_relay.*`.
    3. Carry infra-5's PyPy marker. On WP-2f, `gspread>=5.4.0` sits in `[project].dependencies` (exported to `requirements.txt`), not in the `pipeline` group. Write it there as `gspread>=5.4.0 ; platform_python_implementation != 'PyPy'`, with infra-5's comment, so the exported `requirements.txt` matches this branch. No `cryptography` pin is carried, because infra-5 dropped it.
    4. Run `uv lock` and then `make requirements`. Check that the regenerated `requirements*.txt` contain none of the removed packages and keep the `gspread` marker.
    5. Resolve the `mypy.ini` conflict by taking WP-2f's deletion.

## Contract changes

None.

## Requests

Each request is the exact change verified in unit 4. The combined diff was applied to a scratch copy, and its build and sweep results are under Evidence. None of these block a core unit, so this WP's own units continue.

- [x] **infra**: trim the requirements and the configs that refer to removed packages. Done by infra-5 on `mig/WP-0d-dead-backend-code-infra`, including the optional `python-Levenshtein`. **Merge order:** this branch must land together with or after the backend branch. On its own, `_register_routes` fails with `No module named 'flask_graphql'` (Evidence, infra-5).
  - `requirements-web.txt`: delete `Flask-Admin==1.5.3`, `graphene-sqlalchemy==2.3.0`, `Flask-GraphQL==2.0.1` and `segment-analytics-python==2.2.3`.
  - `requirements-pipeline.txt`: delete `fuzzywuzzy`, `jellyfish==0.7.2`, `editdistance` and `dask==2022.2.0 ; platform_python_implementation != 'PyPy'`.
  - `requirements.txt`: delete `google-cloud-logging==1.11.0 ; ...` and the two-line `# There are issues installing these tools with PyPy...` comment above it.
  - `requirements-dev.txt`: delete lines 1-6, the `# Paramiko deps (used by Fabric)` block: `cryptography==37.0.2`, `pyasn1==0.4.8`, `PyNaCl==1.4.0`, `paramiko==2.7.1`. No repo code imports `cryptography`, `nacl` or `pyasn1`.
  - `mypy.ini`: delete the `[mypy-flask_admin.*]`, `[mypy-flask_graphql.*]`, `[mypy-graphene.*]` and `[mypy-graphene_sqlalchemy.*]` sections (two lines each).
  - `log/config.py`: delete the `'segment'` logger from `DEV_CONFIG['loggers']`. It was the logger for segment-analytics-python.
  - Optional, outside the phase list: `python-Levenshtein==0.12.1` in `requirements.txt` has no importer either. It was fuzzywuzzy's accelerator. Delete it if the lead agrees.
- [x] **backend**: delete the empty GraphQL endpoint. Done by backend-5 on `mig/WP-0d-dead-backend-code-backend`.
  - Delete `web/server/routes/graphql_api.py` and the `web/server/graphql/` package. Its schema is `graphene.Schema()` with no types. `filters.py` and `schemas/` have no importers.
  - In `web/server/app.py` `_register_routes`, delete three lines: `from web.server.routes.graphql_api import GraphqlPageRouter`, `graphql_api_router = GraphqlPageRouter()` and `app.register_blueprint(graphql_api_router.generate_blueprint())`.
  - Leave `/api/timeout` in place (see Phase-file corrections).
  - This WP does not touch `web/server/routes/api.py` (WP-0a and WP-0c).
- [x] **data-platform**: delete the Hadoop ingestion path as one change: `db/druid/indexing/resources/task_templates/`, `db/druid/indexing/resources/tuning_configs/on_prem.json` (the directory's only file), `db/druid/indexing/legacy_task_builder.py` and `db/druid/indexing/scripts/run_indexing.py`. `run_native_indexing.py` and `task_runner_util.py` do not depend on them.
  - Done on `mig/WP-0d-dead-backend-code-druid` (data-platform-2).
  - Also deleted `db/druid/indexing/resources/metrics_spec.json`. Only `legacy_task_builder.py` read it, and it duplicates the inline `metricsSpec` in `db/druid/indexing/common.py:35-40`. `db/druid/indexing/resources/` is now gone.
  - **Accepted by core-2 (2026-10-04).**
    - On `main`, the file holds the same four metrics as the inline `metricsSpec` in `common.py:35-40`: `count`; and `doubleSum`, `doubleMin`, `doubleMax` over `val`, named `sum`, `min`, `max`. Only key order differs.
    - On the merged branch, `git grep metrics_spec` outside `docs/` and `.claude/` finds nothing.
    - Native ingestion builds its spec from `common.py`, so ingested metrics do not change.
- [x] **frontend-platform** (done on `mig/WP-0d-dead-backend-code-frontend`): delete `web/client/util/graphql/zen_environment.js`. In `web/client/util/graphql/index.jsx`, delete the line `import zenEnvironment from 'util/graphql/zen_environment';` and the `zenEnvironment,` export entry. This can land in WP-0e.
- [x] **infra (found during verification; already broken on `main`, not caused by this WP)**: the `etl-pipeline` image does not build. infra-5 on `mig/WP-0d-dead-backend-code-infra`: PyPy failure fixed by marking `gspread>=5.4.0 ; platform_python_implementation != 'PyPy'` in `requirements.txt`. gspread, through google-auth, was the only thing that pulled `cryptography` into the PyPy venv, and nothing in the repo imports gspread. An earlier `cryptography==41.0.7` PyPy pin installed but aborted PyPy 7.3.9 on import (QA finding), so it was dropped. The MinIO 410 is fixed on WP-0b's branch (`mig/WP-0b-ports-secrets-pins`) and is not duplicated here, so this branch's own pipeline build still stops at the `mc` download until WP-0b lands.
  - `docker/pipeline/Dockerfile:29-36` downloads the MinIO client from `https://dl.minio.io/client/mc/release/linux-*/mc`. That URL now returns `HTTP 410 Gone`, so the `downloader` stage fails with `wget` exit 8. This breaks INV-1 for the pipeline image.
  - Suggested fix: pin a versioned `mc` release URL with a SHA-256 check (SEC-9), or copy it from a pinned `minio/mc` image. WP-0b may be the natural home.
  - **Second, independent failure.** Once `mc` is stubbed, the PyPy step fails (`docker/pipeline/Dockerfile:153-159`).
    - `pypy -m pip install --no-build-isolation -r requirements.txt -r requirements-pipeline.txt` resolves `cryptography>=38.0.3` to the `cryptography-47.0.0` sdist. There is no PyPy 3.8 wheel for it, and building it needs `maturin`, which is absent under `--no-build-isolation`.
    - Result: `ModuleNotFoundError: No module named 'maturin'`.
    - Baseline and trimmed builds fail identically. Suggested fix: pin `cryptography` to a version that has a `pp38` wheel in the PyPy install, or drop PyPy as WP-3b plans.
- [ ] **infra (WP-2f)**: bring WP-2f.md's WP-0d hand-off in line with step 3 of this WP's hand-off (under Merge order). The reviewer cites WP-2f.md:83-85 at `c671637`; on the branch head `6ae5d9e` the same block is at WP-2f.md:114-117.
  - Today the block still says to port "the PyPy `cryptography==41.0.7` marker line". infra-5 dropped that pin.
  - Replace that bullet with: carry the PyPy marker onto `gspread` in `[project].dependencies` (`gspread>=5.4.0 ; platform_python_implementation != 'PyPy'`, with infra-5's comment), with no `cryptography` pin.
  - In the mypy bullet, add `graphql_relay` as the fifth override to remove.
  - This does not block WP-0d. It needs to be in place before whichever of the two merges second.
- [x] **lead**: edit `docs/modernisation/phase-0-security-and-subtraction.md` section 0d. Done on `mig/integration`, and this branch picks it up when it next merges `mig/integration`.
  - [x] Drop "Delete the unused `/api/timeout` route". Section 0d now says to keep it.
  - [x] Replace "Point `zen_environment.js` at the Hasura environment, or delete it" with "Delete it".
  - [x] Note that the Hadoop deletion includes `legacy_task_builder.py` and `scripts/run_indexing.py`.
  - [x] Optional: remove the `#Dask` / `dask-worker-space/` lines from `.gitignore`. `7d6c4ad` removed `dask-worker-space/`, and `b06c4bb` ("gitignore: drop the orphaned Dask heading") removed the `#Dask` comment. `mig/integration`'s `.gitignore` no longer matches `dask`.

## Log

- 2026-10-04 core-2 unit 1: claimed WP, recorded path ownership; check: `uv run python scripts/agents/ownership.py who <paths>` (table above).
- 2026-10-04 core-2 unit 2: proved targets dead, found `/api/timeout` live; check: `/tmp/wp0d_dead.sh` transcript under Evidence.
- 2026-10-04 core-2 unit 3: wrote per-owner requests; check: each names files, lines and scope.
- 2026-10-04 core-2 unit 4: verified combined change in scratch copy; check: web-server base/trim build exit 0, sweep diff = deleted modules only, URL map diff = `/graphql` only (Potion 247/247); pipeline CPython install passes base and trim, trimmed sweep 0 removed-package errors; pipeline image itself broken on `main` (mc 410, PyPy maturin), reported to infra.
- 2026-10-04 backend-5: deleted `web/server/routes/graphql_api.py`, the `web/server/graphql/` package and the three `_register_routes` lines in `web/server/app.py`. Added `tests/web/test_graphql_endpoint_removed.py`, plus `tests/web/conftest.py` byte-identical to WP-0c's. Check: the test failed before the deletion (`/graphql` in the rule set) and passes after, in a Python 3.8 env built from `requirements*.txt` minus graphene, Flask-GraphQL and Flask-Admin (none importable); `web.server.app` imports there; `route_map.py` gives 316 rules before and 315 after, the only diff is `/graphql graphql.graphql DELETE,GET,POST,PUT`, and both outputs match core-2's `routes-base.tsv` and `routes-trim.tsv` exactly (247 `/api2` rules; `/api/timeout api.timeout_session POST` present). `git grep` for `graphql_api`, `web.server.graphql`, `GraphqlPageRouter`, `flask_graphql` and `graphene` outside `docs/` finds only the infra-owned `requirements-web.txt` and `mypy.ini` lines.
- 2026-10-04 infra-5 unit 1: trimmed the four requirements files, the 4 mypy sections and the `segment` logger (commit `WP-0d: drop requirements, mypy sections and logger for removed packages`); check: removed-package grep 0 importers outside the backend-deleted modules, web-server image built, sweep and URL map match core-2's trim once the backend deletion is overlaid.
- 2026-10-04 infra-5 unit 2 (superseded): pinned `cryptography==41.0.7` for PyPy. QA at 5f3e040 found it installs but `import cryptography.x509`, `google.auth.crypt` and `gspread` abort PyPy 7.3.9 with `Fatal RPython error: AssertionError` (reproduced by infra-5: exit 139).
- 2026-10-04 infra-5 unit 3: replaced the pin with `gspread ; platform_python_implementation != 'PyPy'` in `requirements.txt`, and removed the dead `[mypy-graphql_relay.*]` section; check: scratch pipeline build with WP-0b's Dockerfile exit 0, PyPy step (`#17 DONE 156.9s`) installs no cryptography/google-auth/gspread and `pip check` is clean, PyPy and CPython sweeps have 0 removed-package errors. Real-branch pipeline build still stops at the `mc` 410 until WP-0b lands.
- 2026-10-04 data-platform-2: deleted the Hadoop ingestion path (`db/druid/indexing/resources/`, `legacy_task_builder.py`, `scripts/run_indexing.py`) on `mig/WP-0d-dead-backend-code-druid` and added `tests/druid/test_hadoop_ingestion_removed.py`; check: grep report has 0 references outside the deleted files, `db/druid` import sweep 41/41 OK, the new test passes on the branch and fails on the pre-deletion tree.
- 2026-10-04 frontend-platform-2: deleted `web/client/util/graphql/zen_environment.js` and its `zenEnvironment` re-export in `index.jsx` (branch `mig/WP-0d-dead-backend-code-frontend`); check: grep for `zen_environment|zenEnvironment` over `web` (excluding build output and node_modules, including flow-typed), `.flowconfig`, `relay.config.js`, `graphql/` and `package.json` finds nothing; Node 24.12 `yarn install --frozen-lockfile --ignore-scripts` then `yarn build` exit 0 with the same two webpack size warnings as before; `flow check` output identical before and after (19 errors); eslint on `index.jsx` clean; `commons` bundle 412 bytes smaller and no longer contains `fetch('/graphql')`, other entries +1 byte (module ids).
- 2026-10-04 core-2 unit 5: merged backend `1e7cfa7`, infra `c310537`, data-platform `2ccbe74`, frontend-platform `ae5d798`, then `mig/integration`. Resolved the WP-file conflicts by keeping all lines, and took the done state of each request checkbox. Accepted the `metrics_spec.json` deletion. Check: the merged web-server image builds; the import sweep (752/625 OK, 0 removed-package errors) and URL map (315 rules) are byte-identical to the scratch `trim`; `tests/web` and `tests/druid` 3 passed (uv, Python 3.8); `tests/infra` 79 passed (uv, Python 3.13).
- 2026-10-05 backend-5, reviewer fix: deleted the tool chain for the removed `/graphql` endpoint. That is `scripts/db/graphql/sync_schema.sh`, which introspected `http://0.0.0.0:5000/graphql` into `graphql/v2/schema.graphql`, the `graphql/v2/` snapshot of the graphene schema, and the `relay-web` npm script in `package.json`. `relay.config.js` and the `relay` script use `graphql/schema.graphql`, which stays. `graphqurl` stays, because `scripts/db/hasura/dev/sync_graphql_schema.sh` still runs `gq`. Check: `git grep -E "relay-web|graphql/v2|sync_schema\.sh|scripts/db/graphql"` over every tracked file (including Makefile, docs, `package.json` and CI) matches nothing outside this WP file; `package.json` parses as JSON.
- 2026-10-05 core-2 unit 6 (review fixes 5-9): merged backend `d0c8f78`. Corrected the `/graphql` reference claim. Recorded the aniso8601 change. Replaced the bulky TSVs with summaries and reran the web sweep with `DRUID_HOST`. Removed the layout-asserting druid test, because WP-8b may add files under `resources/`; the native-indexing import test is kept. Ticked the lead request. Check: rerun web sweep with `DRUID_HOST` gives base 759/690 OK and merged 752/683 OK, 0 removed-package errors, diff = 7 deleted modules; `tests/web` + `tests/druid` 2 passed; ruff and black clean on the edited test.
- 2026-10-05 core-2 unit 7: merged infra `318cd18` (fast-forward), then `mig/integration` (`.playwright-mcp` not tracked). Recorded the WP-2f hand-off under Merge order. Check: the web-server image rebuilt from the final tree builds (exit 0); the `DRUID_HOST` sweep gives 752 modules, 683 OK, 0 removed-package errors, identical to unit 6; the URL map gives 315 rules, identical to unit 5; `tests/web` + `tests/druid` 2 passed (uv, Python 3.8); `tests/infra` 79 passed (uv, Python 3.13); `tests/golden` 269 passed (`uv run pytest`, project env).
- 2026-10-05 core-2 unit 8 (re-review edits, WP file only):
  - The front matter now lists `tests/druid/test_hadoop_ingestion_removed.py` under data-platform-2 only. Core-2's unit 6 edit to it is logged above.
  - backend-5 now claims `scripts/db/graphql/**`, `graphql/v2/**` and `package.json`.
  - Added the infra (WP-2f) request for hand-off step 3. The hand-off is now cited at `c671637`, rechecked at `6ae5d9e`.
  - Corrected the `#Dask` status (removed in `b06c4bb`) and the PyPy Limit note (infra-5 built the PyPy venv; the change adds the `gspread` marker).
  - Merged `mig/integration`.
  - Check: no code changed; `git grep gspread -- '*.py'` finds 0 importers.

## Evidence

### infra-5: requirements trim and PyPy fix

Branch `mig/WP-0d-dead-backend-code-infra`, built from the WP branch with `mig/integration` merged. The six-file trim matches core-2's scratch `combined.diff` (since deleted; the merged branch diff supersedes it) line for line, plus `python-Levenshtein==0.12.1`.

**Nothing imports a removed package.** [`infra5_grep.sh`](WP-0d-evidence/infra5_grep.sh) excludes `docs/`, `.claude/`, VCS metadata and `node_modules`. Output: [`infra5_grep.out`](WP-0d-evidence/infra5_grep.out).
- `flask_admin`, `dask`, `google`, `segment`, `analytics`, `paramiko`, `nacl`, `pyasn1`, `fuzzywuzzy`, `jellyfish`, `editdistance`, `Levenshtein`, `fabric` and `cryptography` have 0 importers.
- `graphene`, `graphene_sqlalchemy`, `flask_graphql` and `graphql` are imported only by `web/server/graphql/` and `web/server/routes/graphql_api.py`, which the backend request deletes.
- The only other textual mention is `.gitignore:216-217` (`dask-worker-space/`), which is in the lead's optional request.

**`web-server` image.** Built with `DOCKER_NAMESPACE=local/wp0d-infra5 DOCKER_TAG=web docker compose -p wp0d-infra5-web -f docker-compose.build.yaml build web-server`. Exit 0.
- It prints the same pre-existing `typing-extensions 4.1.1` resolver warning as core-2's base build.
- Of the removed packages, `pip list` shows only `cryptography 47.0.0` and `pyasn1 0.6.4`. Both arrive transitively through `google-auth`, and nothing in the repo imports either one.
- **Import sweep** with core-2's [`import_sweep.py`](WP-0d-evidence/import_sweep.py), run as `docker run --rm --network none -e PYTHONPATH=/zenysis -e ZEN_ENV=harmony_demo -e DEFAULT_SECRET_KEY=<dummy> ...`. Output is sorted, with stray stdout lines dropped.

| Run | Modules | OK | Removed-package errors |
|---|---|---|---|
| infra branch alone ([tsv](WP-0d-evidence/sweep-web-infra5.tsv)) | 759 | 628 | 3: `web.server.graphql.filters`, `web.server.graphql.schema`, `web.server.routes.graphql_api` |
| infra branch plus the backend deletion, as a read-only `web/server` bind mount ([tsv](WP-0d-evidence/sweep-web-infra5-backend.tsv)) | 754 | 626 | 0 |

- Against core-2's base sweep, the branch alone differs only in those 3 modules. With the backend deletion overlaid, it differs from core-2's trim sweep only in `db.druid.indexing.legacy_task_builder` and `scripts.run_indexing`. Those two are data-platform's deletion, which was not overlaid.
- **URL map.** core-2's [`route_map.py`](WP-0d-evidence/route_map.py) also needs dummy `DRUID_HOST`, `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD` and `DATABASE_URL`.
  - The branch alone exits 1 with `ModuleNotFoundError: No module named 'flask_graphql'`, raised from `_register_routes`. This is why the merge order matters.
  - With the backend overlay it produces 315 rules, byte-identical to core-2's scratch `routes-trim.tsv` (counts and diff in [`routes-summary.txt`](WP-0d-evidence/routes-summary.txt)).
- `log/config.py`: `logging.config.dictConfig(DEV_CONFIG)` loads, `black -S --check` (22.6.0) passes, and `ruff check --select F` passes.

**`etl-pipeline` image.**
- **This branch as committed:** `DOCKER_NAMESPACE=local/wp0d-infra5 DOCKER_TAG=pipe docker compose -p wp0d-infra5-pipe -f docker-compose.build.yaml build etl-pipeline` stops at step `#8`, the `downloader` stage `mc` download, with `ERROR 410: Gone` (`wget` exit 8). This is the `main` breakage that WP-0b fixes. The build never reaches pip.
- **Scratch copy** (a copy of the branch tree, never committed) with WP-0b's `docker/pipeline/Dockerfile` swapped in and `ENV PIP_DEFAULT_TIMEOUT=300` added after a transient PyPI read timeout. The harness diff is [`infra5-pipeline-harness.diff`](WP-0d-evidence/infra5-pipeline-harness.diff), and no requirement line differs from this branch. Image built, exit 0:
  - WP-0b's `mc` download and `sha256sum -c` passed.
  - CPython venv step `#15 DONE 677.1s`.
  - PyPy venv step `#17 DONE 156.9s`. Its only mention of the packages involved is `Ignoring gspread: markers 'platform_python_implementation != "PyPy"' don't match your environment`. No cryptography download, no sdist build and no maturin.
  - PyPy venv: `pip list` has no `cryptography`, `google-auth`, `gspread`, `pyasn1` or `rsa`, and `pip check` reports `No broken requirements found.` The CPython venv is unchanged: `gspread 6.2.1`, `google-auth 2.50.0` and `cryptography 45.0.7`.
- **Import sweep** over `pipeline data util db config models log` in both venvs, run with `--network none` and dummy environment values, on the WP branch tree (Hadoop files already deleted):

| Venv | Modules | OK | Removed-package errors |
|---|---|---|---|
| CPython ([tsv](WP-0d-evidence/sweep-pipeline-infra5-cpython.tsv)) | 398 | 392 | 0 |
| PyPy ([tsv](WP-0d-evidence/sweep-pipeline-infra5-pypy.tsv)) | 398 | 384 | 0 |

- The CPython sweep differs from core-2's trim sweep only by `config.template.ui` (`MAPBOX_ACCESS_TOKEN` unset in my run).
- The PyPy sweep has 8 more failures than CPython. Each one is a package that `requirements.txt` already excludes under PyPy: `pandas`, `psycopg2`, and `flask_login` through `flask-user`. No swept module imports gspread, google-auth or cryptography.
- This is the first PyPy evidence for WP-0d. Before this fix, core-2 could not build the PyPy venv.

**Why the marker and not a pin.**
- The first fix pinned `cryptography==41.0.7` under PyPy. It was the last release with pp38 wheels, and it installed. Importing it, however, aborts Ubuntu 22.04's PyPy 7.3.9 with `Fatal RPython error: AssertionError PyThreadState_Swap()`. QA saw exit 134, and infra-5 reproduced it with exit 139 on `cryptography.x509`, `google.auth.crypt` and `gspread`.
- QA's reverse-dependency check found that gspread, through google-auth, is the only reason cryptography enters the PyPy venv. A grep for `gspread`, `google.auth`, `google.oauth2` and `oauth2client` across the repo, outside docs, finds no importer at all. Leaving gspread out of PyPy therefore costs nothing and removes the native extension.
- The same marker applies to the dev image's PyPy 7.3.11 install.
- Whether to delete gspread outright, since it is also unused under CPython, is a separate call that WP-0d does not make.

### Unit 2: the targets are dead

Command: a grep over the repo, excluding `docs/`, `.claude/` and `node_modules`. It is the script `/tmp/wp0d_dead.sh`, reproduced in the steps below.

- **Imports of the removed packages** (`^\s*(import|from)\s+<name>(\.|\s|$)`, over `*.py`):
  - `flask_admin`, `dask`, `google`, `segment`, `analytics`, `paramiko`, `nacl`, `pyasn1`, `cryptography`, `fuzzywuzzy`, `jellyfish`, `editdistance`, `Levenshtein` and `fabric` have 0 importers each.
  - `graphene`, `graphene_sqlalchemy` and `flask_graphql` are imported only by the modules being deleted: `web/server/graphql/{filters,schema}.py` and `web/server/routes/graphql_api.py`.
  - `graphql` (graphql-core, a transitive dependency of graphene) is imported only by `web/server/graphql/filters.py`.
- **Textual mentions** outside `requirements*.txt` and `mypy.ini`:
  - `.gitignore:216-217` (`dask-worker-space/`).
  - `log/config.py:18`, the `segment` logger.
  - npm `*levenshtein` packages in `yarn.lock` and flow-typed stubs. These are unrelated JavaScript packages.
  - Two docstring mentions of "Google Cloud Storage" in `util/dataprep/utils.py`. These are prose, not imports.
- **The `/graphql` route.** *Corrected 2026-10-04 after QA and reviewer review.* The unit 2 grep searched only module names (`graphql_api`, `GraphqlPageRouter`), never the URL. Those module names occur only in `web/server/app.py:61,83,94`.
  - `git grep` on `main` for the URL `/graphql` (excluding `/api/graphql` and `/v1/graphql`, `docs/`, `.claude/` and `yarn.lock`) finds three references:
    - `web/server/routes/graphql_api.py:21`, the route itself;
    - `web/client/util/graphql/zen_environment.js:22`, which is unused (see below);
    - `scripts/db/graphql/sync_schema.sh:11`, a developer tool. It introspects `http://0.0.0.0:5000/graphql` into `graphql/v2/schema.graphql`. Its only consumer is the `relay-web` npm script (`package.json:156`, `relay-compiler --schema ./graphql/v2/schema.graphql`).
  - Without the endpoint the tool chain is dead. It is routed to backend-5 for deletion: `scripts/db/graphql/`, `graphql/v2/` and the `relay-web` script.
  - No nginx or compose config routes `/graphql`.
- **`/api/timeout`** is live: see Phase-file corrections.
- **The Hadoop templates** are reached only through `legacy_task_builder.py`, which only `scripts/run_indexing.py` imports, and nothing references that script.
- **`zenEnvironment`** is used only by its re-export in `web/client/util/graphql/index.jsx`.
- **Files:**
  - The grep script and its output: [`WP-0d-evidence/wp0d_dead.sh`](WP-0d-evidence/wp0d_dead.sh) and [`wp0d_dead.out`](WP-0d-evidence/wp0d_dead.out).
  - Two further greps: `ZenClient.post('timeout'` in `web/client/util/timeoutSession.js:42`, and `fetch('/api/graphql'` in `util/graphql/environment.js:22`.

### Unit 4: the combined change builds and imports

**Method.**
- `git archive HEAD` was unpacked twice under `/tmp/wp0d-core2/`, as `base` and `trim`.
- The exact change from the Requests section was applied to `trim`. The result was `combined.diff` (`diff -ru base trim`). It was deleted in unit 6, because the merged branch diff against `main` now shows the same change. That copy is never committed and edits no owned path in this branch.
- Images were built with `DOCKER_NAMESPACE=local/wp0d-core2-<v> DOCKER_TAG=<v> docker compose -p wp0d-core2-<v> -f docker-compose.build.yaml build <service>`.

**`web-server` image.**
- Both `base` and `trim` build (exit 0).
- Both print the same pip warning: `typing-extensions 4.1.1` conflicts with `exceptiongroup` and `cryptography 47`. This is pre-existing and not caused by the change.
- `cryptography` is still installed transitively in `trim`.

**Import sweep.**
- Script: [`import_sweep.py`](WP-0d-evidence/import_sweep.py). It imports every module under `config data db log models util web`, without `web/client` or `web/public`.
- Command: `docker run --rm --network none -e ZEN_ENV=harmony_demo -e DEFAULT_SECRET_KEY=<dummy> <image> python /sweep.py`.

| Image | Modules | OK | Errors from a removed package |
|---|---|---|---|
| base | 759 | 631 | 0 |
| trim | 752 | 625 | 0 |

- `diff` of the two outputs (counts and diff in [`sweep-web-summary.txt`](WP-0d-evidence/sweep-web-summary.txt)) differs only by the deleted modules:
  - `db.druid.indexing.legacy_task_builder`
  - `db.druid.indexing.scripts.run_indexing`, which already failed on base with `KeyError: 'DRUID_HOST'`
  - `web.server.graphql`, `web.server.graphql.filters`, `web.server.graphql.schema` and `web.server.graphql.schemas`
  - `web.server.routes.graphql_api`
- Every other module has the same status in both images. The remaining errors exist on both images: missing pipeline-only packages in the web image, Flask app-context access at import, and mapper initialisation without a database.
- **Limit of this run (raised in review, fixed in unit 6).** This run did not set `DRUID_HOST`. In the trimmed image, 69 of 752 modules (70 of 759 on base) stopped at `KeyError: 'DRUID_HOST'` before importing the rest of their dependencies, so they were not checked for removed packages.
  - Unit 6 reran both images with `-e DRUID_HOST=http://druid.invalid`. Then 0 modules stop on it.
  - Base: 759 modules, 690 OK. Merged: 752 modules, 683 OK.
  - Neither has an error from a removed package, and the diff is still exactly the 7 deleted modules. See [`sweep-web-summary.txt`](WP-0d-evidence/sweep-web-summary.txt), run 2.

**URL map.**
- Script: [`route_map.py`](WP-0d-evidence/route_map.py). It builds the app with `create_app(skip_db_check=True)`, mocks `template_renderer` and `druid_context`, runs the real `_initialize_query_data`, and then runs the real `_register_routes`, which includes Potion.
- Run with `--network none` and dummy environment values.
- Base has 316 rules and trim has 315. The 247 Potion `/api2` rules are identical.
- The [diff](WP-0d-evidence/routes-summary.txt) shows that the only change is the removal of `/graphql  graphql.graphql  DELETE,GET,POST,PUT`. `/api/timeout  api.timeout_session  POST` is still present in trim.

**`etl-pipeline` image.** It cannot build on `main` today, for two pre-existing reasons recorded under Requests (infra).
- To verify around them, the scratch copy changes only harness lines, and the requirement lines are untouched. See [`pipeline-harness-only.diff`](WP-0d-evidence/pipeline-harness-only.diff):
  - the dead `mc` download is stubbed;
  - `PIP_DEFAULT_TIMEOUT=300` is set, after one transient download timeout on `savReaderWriter`;
  - the CPython-only variant also drops the PyPy venv.
- Results:

| Build | CPython venv: `requirements.txt` + `requirements-pipeline.txt` | PyPy venv |
|---|---|---|
| base, harness only | `#15 DONE 507.2s` | fails: `No module named 'maturin'` (cryptography 47 sdist) |
| trim, harness only | `#15 DONE 465.5s` | fails identically |
| trim, CPython-only variant | image built (exit 0) | not built |

- **Import sweep** in the CPython-only trimmed image (`/zenysis/venv/bin/python import_sweep.py pipeline data util db config models log`, `--network none`, dummy environment):
  - 398 modules: 393 OK, and none failed because of a removed package. Counts and every non-OK module: [`sweep-pipeline-trim-summary.txt`](WP-0d-evidence/sweep-pipeline-trim-summary.txt).
  - The 5 failures have nothing to do with this WP. Four modules call Druid at import time and get `ConnectionError` to `druid.invalid`: `config/harmony_demo/database.py`, `config/template/database.py`, `data/pydruid_query/pydruid_query.py` and `data/validation/scripts/validate_pivoted_csv.py`. That is a BE-2 item for WP-4a. The fifth is a mapper ordering error in `data.query.models.query_selections`.
- **Limit of core-2's unit 4 run.** I could not show PyPy resolution here, because of the pre-existing `cryptography`/`maturin` failure.
  - *Superseded 2026-10-05:* infra-5 did build the PyPy venv, using WP-0b's Dockerfile in a scratch copy (see the infra-5 Evidence and log).
  - The final change also does more than remove lines. It adds `; platform_python_implementation != 'PyPy'` to `gspread>=5.4.0` in `requirements.txt`, so PyPy installs no `gspread` and no `cryptography`. Nothing in the repo imports `gspread`.

**Not run.**
- The end-to-end smoke list from `testing.md` (`e2e/`) does not exist yet (WP-2e). In its place: the URL-map diff and the import sweeps above.
- core-2 did not run `yarn build` for the front-end half (`zen_environment.js`). frontend-platform-2 did: Node 24.12, `yarn install --frozen-lockfile --ignore-scripts`, then `yarn build`, exit 0. Its `flow check` output is unchanged, and the `commons` bundle is 412 bytes smaller. See the frontend-platform-2 log line.
- Lint and type checks on core-2's own commits: none needed, since they change no Python. The Python changes from the other roles are linted by their owners (see their log lines and Evidence sections).

### core-2 unit 5: the integrated branch

This was run on the merged head, which holds all four side branches plus `mig/integration`. The tree was exported with `git archive HEAD`, never committed, to `/tmp/wp0d-core2/merged`.

**Leftover references.** `git grep -i` for every removed package name, plus `graphql_api`, `GraphqlPageRouter`, `web.server.graphql`, `legacy_task_builder`, `task_templates`, `on_prem.json` and `zen_environment|zenEnvironment`.
- Scope: excludes `docs/`, `.claude/`, `yarn.lock`, `web/public/js/vendor` and `tests/`.
- The only hits are `.gitignore:216-217` (`dask-worker-space/`), which is in the lead's optional request.
- All deleted paths are absent. `/api/timeout` is still registered in `web/server/routes/api.py:405`.

**`web-server` image.** Built with `DOCKER_NAMESPACE=local/wp0d-core2-merged DOCKER_TAG=merged docker compose -p wp0d-core2-merged -f docker-compose.build.yaml build web-server`. Exit 0.

| Check | Result | Same as the verified scratch `trim`? |
|---|---|---|
| Import sweep without `DRUID_HOST` ([summary](WP-0d-evidence/sweep-web-summary.txt), run 1) | 752 modules, 625 OK, 0 removed-package errors; 69 stop at `KeyError: 'DRUID_HOST'` | yes: `diff sweep-web-trim.tsv sweep-web-merged.tsv` is empty |
| Import sweep with `DRUID_HOST=http://druid.invalid` (same summary, run 2; unit 6) | 752 modules, 683 OK, 0 removed-package errors; 0 stop at `DRUID_HOST` | against base (759, 690 OK), only the 7 deleted modules differ |
| URL map ([summary](WP-0d-evidence/routes-summary.txt)) | 315 rules, 247 `/api2`, `/api/timeout api.timeout_session POST` present, no `/graphql` | yes: `diff routes-trim.tsv routes-merged.tsv` is empty |

**Test suites, with uv.** There is no pyproject yet, so the web environment is built from the merged `requirements.txt` and `requirements-web.txt`. `-e git+…#egg=X` lines are rewritten to `X @ git+…`, as in backend-5's recipe.
- `PYTHONPATH=<worktree> uv run --no-project -p 3.8 --with-requirements /tmp/wp0d-core2/reqs-web.txt --with 'pytest<8' python -m pytest tests/web tests/druid -q -p no:cacheprovider -W ignore` gives **3 passed**:
  - `test_graphql_endpoint_is_not_registered`
  - `test_hadoop_ingestion_modules_are_gone`
  - `test_native_indexing_imports_without_druid`
- `uv run --no-project -p 3.13 --with pytest python -m pytest tests/infra -q -p no:cacheprovider` gives **79 passed**. `prod/browser_share/browser_share.py` declares `requires-python >=3.13`.

### core-2 unit 6: review fixes (QA and reviewer, changes-requested at `5f3e040`)

- **Item 5, `/graphql` references.** Corrected under Unit 2 below. The URL grep found `scripts/db/graphql/sync_schema.sh` and the `relay-web` npm script. backend-5 deleted them in `d0c8f78`, merged here as `8cfbbaf`. The only `/graphql` match left outside `docs/` is the assertion in `tests/web/test_graphql_endpoint_removed.py:18`.
- **Item 6, aniso8601.** Dropping graphene removes the `<8` cap on aniso8601, so the web image moves from 7.0.0 to 10.0.1, which Flask-Potion pulls in unpinned.
  - Probe: `aniso_probe.py` (`/tmp/wp0d-core2/aniso_probe.py`), run through Potion's `DateString` and `DateTimeString` converters in both images. The repo has 12 such fields and no direct aniso8601 import.
  - Valid ISO dates and datetimes parse identically.
  - Malformed input still raises a `ValueError` subclass, but with a different class or message, for example `MonthOutOfBoundsError: Month must be between 1..12.` where it used to be `ValueError: month must be in 1..12`.
- **Item 7, evidence trimmed.**
  - The web, route and pipeline TSVs and `combined.diff` are replaced by [`sweep-web-summary.txt`](WP-0d-evidence/sweep-web-summary.txt), [`routes-summary.txt`](WP-0d-evidence/routes-summary.txt) and [`sweep-pipeline-trim-summary.txt`](WP-0d-evidence/sweep-pipeline-trim-summary.txt), each with counts and the base-to-trim diff.
  - The scripts and the small grep outputs stay. infra-5's and data-platform-2's TSVs are theirs and stay.
  - The `DRUID_HOST` gap of the first web sweep is stated, and the sweep was rerun, as described under Unit 4.
- **Item 8, druid test.** Removed `test_hadoop_ingestion_modules_are_gone` from `tests/druid/test_hadoop_ingestion_removed.py`. It asserted repository layout: `db/druid/indexing/resources/` must not exist, and two module names must not resolve. WP-8b may legitimately add files under `resources/`, and the import sweep already proves the modules are gone.
  - `test_native_indexing_imports_without_druid` stays.
  - Check: `uvx ruff check` and `black==22.6.0 -S --check` are clean. `tests/web` and `tests/druid` give **2 passed** (uv, Python 3.8, merged requirements).
- **Item 9.** The lead request is ticked. The phase 0d text and the `.gitignore` edit are on `mig/integration`, and the orphaned `#Dask` comment was later removed in `b06c4bb`.

### core-2 unit 7: the final integrated tree

The tree is the merged head after infra `318cd18` and `mig/integration`, exported with `git archive HEAD` to `/tmp/wp0d-core2/merged2`. The image was built with `DOCKER_NAMESPACE=local/wp0d-core2-merged2 DOCKER_TAG=merged2 docker compose -p wp0d-core2-merged2 -f docker-compose.build.yaml build web-server`.

| Check | Result |
|---|---|
| web-server image build | exit 0, with the same pre-existing `typing-extensions` warning. CPython still installs `gspread`, because the marker excludes it only under PyPy. |
| Import sweep, `DRUID_HOST=http://druid.invalid` | 752 modules, 683 OK, 0 removed-package errors, 0 stop at `DRUID_HOST`. Byte-identical to unit 6's merged run ([`sweep-web-summary.txt`](WP-0d-evidence/sweep-web-summary.txt), run 2). |
| URL map | 315 rules, 247 `/api2`, `/api/timeout api.timeout_session POST` present, no `/graphql`. Byte-identical to unit 5 ([`routes-summary.txt`](WP-0d-evidence/routes-summary.txt)). |
| `tests/web` + `tests/druid` (uv, Python 3.8, requirements rebuilt from this tree) | 2 passed |
| `tests/infra` (uv, Python 3.13) | 79 passed |
| `tests/golden` (`uv run pytest tests/golden`, project env from `mig/integration`) | 269 passed |

### data-platform-2: the Hadoop ingestion path is deleted

Branch `mig/WP-0d-dead-backend-code-druid`. It was created from `mig/WP-0d-dead-backend-code` and merged with `mig/integration`.

**Grep report.**
- Script: [`dp2_hadoop_grep.sh`](WP-0d-evidence/dp2_hadoop_grep.sh). Output after the deletion: [`dp2_hadoop_grep.out`](WP-0d-evidence/dp2_hadoop_grep.out).
- Pattern: `legacy_task_builder`, `run_indexing`, `task_templates`, `index_hadoop`, `on_prem.json`, `tuning_configs` and `DruidIndexingTaskBuilder`.
- There are 0 hits in `pipeline`, `prod`, `docker`, `Makefile`, `scripts`, `.github`, `druid_setup`, `config`, `web`, `data`, `db`, `util`, `models` and `log`.
- Across the whole repo (excluding `docs` and `.claude`), the only hits are the module names in the new test.
- Nothing outside the deleted builder refers to `db/druid/indexing/resources/` or `metrics_spec.json`.
- `task_runner_util.py` has its own `_validate_file_path` and still uses `BadIndexingPathException` from `db/druid/errors.py`.

**Import sweep.**
- Script: core-2's [`import_sweep.py`](WP-0d-evidence/import_sweep.py), run over `db/druid`.
- Image: `local/wp0d-core2-trim/etl-pipeline-cpython:trim`, with the branch mounted at `/src`.
- Run with `--network none`, `ZEN_ENV=harmony_demo`, `DRUID_HOST=http://druid.invalid` and a dummy `DEFAULT_SECRET_KEY`.
- Result: 41 modules, all OK. These include `db.druid.indexing.{common,minio_task_builder,task_runner_util}` and `db.druid.indexing.scripts.{fetch_status,run_compaction,run_native_indexing}`.
- Output: [`dp2_sweep-db-druid.tsv`](WP-0d-evidence/dp2_sweep-db-druid.tsv).

**Test.** `tests/druid/test_hadoop_ingestion_removed.py` ran in the same image, with `pytest==8.3.5` installed into the throwaway container.
- On the branch: 2 passed.
- On the pre-deletion tree (a `git archive` of the branch before the deletion, plus the test):
  - `test_hadoop_ingestion_modules_are_gone` fails on `find_spec('db.druid.indexing.legacy_task_builder')`;
  - `test_native_indexing_imports_without_druid` passes.

**Lint.** `uvx black --check -S` and `uvx ruff check` report no issues on the test.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-05 qa-0d at 51cd30e: files lists cover the diff and do not overlap; code identical to the eb2d023 tree fully re-verified (images, sweeps, 315-rule route map, suites, 540 contract replays, PyPy installs no cryptography and imports fail cleanly); merges cleanly into integration. |
| reviewer | approved | 2026-10-05 rev-0d final check at 51cd30e: all eight original and three re-review findings closed; code unchanged since eb2d023; branch merges cleanly with integration. Open, non-blocking: WP-2f must update its porting note before whichever of 0d/2f merges second. |
| security | n/a | |
