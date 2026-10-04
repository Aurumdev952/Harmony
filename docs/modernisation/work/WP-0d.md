---
wp: "0d"
title: "Delete dead backend code and dependencies"
status: review
owner_role: "core"
instances:
  - name: "core-2"
    files:
      - docs/modernisation/work/WP-0d.md
      - docs/modernisation/work/WP-0d-evidence/**
  - name: "infra-5"
    files:
      - requirements.txt
      - requirements-web.txt
      - requirements-pipeline.txt
      - requirements-dev.txt
      - mypy.ini
      - log/config.py
      - docs/modernisation/work/WP-0d-evidence/infra5*
      - docs/modernisation/work/WP-0d-evidence/sweep-*infra5*
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

At the lead's instruction on 2026-10-04, this branch merges `mig/decisions-0001-ownership` (merge commit `35e9d62`). The diff against `main` therefore includes that branch's `docs/modernisation/SPEC.md` and `docs/modernisation/decisions/0001-*.md` changes. They are not WP-0d edits, and they drop out once the decision branch lands on `main`. `task_gate.py` flags `SPEC.md` (owner: lead) for this reason only.

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
- [ ] **backend**: delete the empty GraphQL endpoint.
  - Delete `web/server/routes/graphql_api.py` and the `web/server/graphql/` package. Its schema is `graphene.Schema()` with no types. `filters.py` and `schemas/` have no importers.
  - In `web/server/app.py` `_register_routes`, delete three lines: `from web.server.routes.graphql_api import GraphqlPageRouter`, `graphql_api_router = GraphqlPageRouter()` and `app.register_blueprint(graphql_api_router.generate_blueprint())`.
  - Leave `/api/timeout` in place (see Phase-file corrections).
  - This WP does not touch `web/server/routes/api.py` (WP-0a and WP-0c).
- [ ] **data-platform**: delete the Hadoop ingestion path as one change: `db/druid/indexing/resources/task_templates/`, `db/druid/indexing/resources/tuning_configs/on_prem.json` (the directory's only file), `db/druid/indexing/legacy_task_builder.py` and `db/druid/indexing/scripts/run_indexing.py`. `run_native_indexing.py` and `task_runner_util.py` do not depend on them.
- [ ] **frontend-platform**: delete `web/client/util/graphql/zen_environment.js`. In `web/client/util/graphql/index.jsx`, delete the line `import zenEnvironment from 'util/graphql/zen_environment';` and the `zenEnvironment,` export entry. This can land in WP-0e.
- [x] **infra (found during verification; already broken on `main`, not caused by this WP)**: the `etl-pipeline` image does not build. infra-5 on `mig/WP-0d-dead-backend-code-infra`: PyPy failure fixed with `cryptography==41.0.7 ; platform_python_implementation == 'PyPy'` in `requirements-pipeline.txt`. The MinIO 410 is fixed on WP-0b's branch (`mig/WP-0b-ports-secrets-pins`) and is not duplicated here, so this branch's own pipeline build still stops at the `mc` download until WP-0b lands.
  - `docker/pipeline/Dockerfile:29-36` downloads the MinIO client from `https://dl.minio.io/client/mc/release/linux-*/mc`. That URL now returns `HTTP 410 Gone`, so the `downloader` stage fails with `wget` exit 8. This breaks INV-1 for the pipeline image.
  - Suggested fix: pin a versioned `mc` release URL with a SHA-256 check (SEC-9), or copy it from a pinned `minio/mc` image. WP-0b may be the natural home.
  - **Second, independent failure.** Once `mc` is stubbed, the PyPy step fails (`docker/pipeline/Dockerfile:153-159`).
    - `pypy -m pip install --no-build-isolation -r requirements.txt -r requirements-pipeline.txt` resolves `cryptography>=38.0.3` to the `cryptography-47.0.0` sdist. There is no PyPy 3.8 wheel for it, and building it needs `maturin`, which is absent under `--no-build-isolation`.
    - Result: `ModuleNotFoundError: No module named 'maturin'`.
    - Baseline and trimmed builds fail identically. Suggested fix: pin `cryptography` to a version that has a `pp38` wheel in the PyPy install, or drop PyPy as WP-3b plans.
- [ ] **lead**: edit `docs/modernisation/phase-0-security-and-subtraction.md` section 0d.
  - Drop "Delete the unused `/api/timeout` route".
  - Replace "Point `zen_environment.js` at the Hasura environment, or delete it" with "Delete it".
  - Note that the Hadoop deletion includes `legacy_task_builder.py` and `scripts/run_indexing.py`.
  - Optional: remove the `#Dask` / `dask-worker-space/` lines from `.gitignore`.

## Log

- 2026-10-04 core-2 unit 1: claimed WP, recorded path ownership; check: `uv run python scripts/agents/ownership.py who <paths>` (table above).
- 2026-10-04 core-2 unit 2: proved targets dead, found `/api/timeout` live; check: `/tmp/wp0d_dead.sh` transcript under Evidence.
- 2026-10-04 core-2 unit 3: wrote per-owner requests; check: each names files, lines and scope.
- 2026-10-04 core-2 unit 4: verified combined change in scratch copy; check: web-server base/trim build exit 0, sweep diff = deleted modules only, URL map diff = `/graphql` only (Potion 247/247); pipeline CPython install passes base and trim, trimmed sweep 0 removed-package errors; pipeline image itself broken on `main` (mc 410, PyPy maturin), reported to infra.
- 2026-10-04 infra-5 unit 1: trimmed the four requirements files, the 4 mypy sections and the `segment` logger (commit `WP-0d: drop requirements, mypy sections and logger for removed packages`); check: removed-package grep 0 importers outside the backend-deleted modules, web-server image built, sweep and URL map match core-2's trim once the backend deletion is overlaid.
- 2026-10-04 infra-5 unit 2: pinned `cryptography==41.0.7` for PyPy in `requirements-pipeline.txt`; check: scratch pipeline build with WP-0b's Dockerfile exit 0, PyPy step installs the pp38 wheel, PyPy and CPython sweeps have 0 removed-package errors. Real-branch pipeline build stops at the `mc` 410, which WP-0b fixes.

## Evidence

### infra-5: requirements trim and PyPy pin

Branch `mig/WP-0d-dead-backend-code-infra`, built from the WP branch with `mig/integration` merged. The six-file trim matches core-2's [`combined.diff`](WP-0d-evidence/combined.diff) line for line, plus `python-Levenshtein==0.12.1`.

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
  - With the backend overlay it produces 315 rules, byte-identical to core-2's [`routes-trim.tsv`](WP-0d-evidence/routes-trim.tsv).
- `log/config.py`: `logging.config.dictConfig(DEV_CONFIG)` loads, `black -S --check` (22.6.0) passes, and `ruff check --select F` passes.

**`etl-pipeline` image.**
- **This branch as committed:** `DOCKER_NAMESPACE=local/wp0d-infra5 DOCKER_TAG=pipe docker compose -p wp0d-infra5-pipe -f docker-compose.build.yaml build etl-pipeline` stops at step `#8`, the `downloader` stage `mc` download, with `ERROR 410: Gone` (`wget` exit 8). This is the `main` breakage that WP-0b fixes. The build never reaches pip.
- **Scratch copy** (`git archive HEAD`, never committed) with WP-0b's `docker/pipeline/Dockerfile` swapped in and `ENV PIP_DEFAULT_TIMEOUT=300` added after a transient PyPI read timeout. The harness diff is [`infra5-pipeline-harness.diff`](WP-0d-evidence/infra5-pipeline-harness.diff), and no requirement line differs from this branch. Image built, exit 0:
  - WP-0b's `mc` download and `sha256sum -c` passed.
  - CPython venv step `#15 DONE 664.3s`.
  - PyPy venv step `#17 DONE 276.2s`. It picked `cryptography-41.0.7-pp38-pypy38_pp73-manylinux_2_28_x86_64.whl`, and no maturin build ran.
  - Installed `cryptography`: CPython 45.0.7 (unpinned, unchanged), PyPy 41.0.7.
- **Import sweep** over `pipeline data util db config models log` in both venvs, run with `--network none` and dummy environment values:

| Venv | Modules | OK | Removed-package errors |
|---|---|---|---|
| CPython ([tsv](WP-0d-evidence/sweep-pipeline-infra5-cpython.tsv)) | 400 | 394 | 0 |
| PyPy ([tsv](WP-0d-evidence/sweep-pipeline-infra5-pypy.tsv)) | 400 | 386 | 0 |

- The CPython sweep differs from core-2's trim sweep only by the two Hadoop modules (not overlaid) and `config.template.ui` (`MAPBOX_ACCESS_TOKEN` unset in my run).
- The PyPy sweep has 8 more failures than CPython. Each one is a package that `requirements.txt` already excludes under PyPy: `pandas`, `psycopg2`, and `flask_login` through `flask-user`.
- This is the first PyPy evidence for WP-0d. Before the pin, core-2 could not build the PyPy venv.

**Why 41.0.7.** PyPI shows `pp38` wheels for cryptography up to 41.0.7 and none for 42.0.0 or later. Ubuntu 22.04's `pypy3` is PyPy 7.3.9 (Python 3.8). 41.0.7 also has `pp39` and `pp310` wheels for x86_64 and aarch64. The pin therefore also suits the dev image's PyPy 7.3.11 (Python 3.9), which installs the same file and would otherwise hit the same maturin build once cryptography passes 43.x. Restricting the pin with a PyPy marker leaves CPython's resolution unchanged.

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
- **The `/graphql` route** is referenced only from `web/server/app.py:61,83,94`. The only client that calls `/graphql` is `zen_environment.js`, and that file is itself unused. No nginx or compose config routes `/graphql`.
- **`/api/timeout`** is live: see Phase-file corrections.
- **The Hadoop templates** are reached only through `legacy_task_builder.py`, which only `scripts/run_indexing.py` imports, and nothing references that script.
- **`zenEnvironment`** is used only by its re-export in `web/client/util/graphql/index.jsx`.
- **Files:**
  - The grep script and its output: [`WP-0d-evidence/wp0d_dead.sh`](WP-0d-evidence/wp0d_dead.sh) and [`wp0d_dead.out`](WP-0d-evidence/wp0d_dead.out).
  - Two further greps: `ZenClient.post('timeout'` in `web/client/util/timeoutSession.js:42`, and `fetch('/api/graphql'` in `util/graphql/environment.js:22`.

### Unit 4: the combined change builds and imports

**Method.**
- `git archive HEAD` was unpacked twice under `/tmp/wp0d-core2/`, as `base` and `trim`.
- The exact change from the Requests section was applied to `trim`. The result is [`WP-0d-evidence/combined.diff`](WP-0d-evidence/combined.diff) (`diff -ru base trim`). That copy is never committed and edits no owned path in this branch.
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

- `diff` of the two outputs ([base](WP-0d-evidence/sweep-web-base.tsv), [trim](WP-0d-evidence/sweep-web-trim.tsv)) differs only by the deleted modules:
  - `db.druid.indexing.legacy_task_builder`
  - `db.druid.indexing.scripts.run_indexing`, which already failed on base with `KeyError: 'DRUID_HOST'`
  - `web.server.graphql`, `web.server.graphql.filters`, `web.server.graphql.schema` and `web.server.graphql.schemas`
  - `web.server.routes.graphql_api`
- Every other module has the same status in both images. The remaining errors exist on both images: missing pipeline-only packages in the web image, Flask app-context access at import, and mapper initialisation without a database.

**URL map.**
- Script: [`route_map.py`](WP-0d-evidence/route_map.py). It builds the app with `create_app(skip_db_check=True)`, mocks `template_renderer` and `druid_context`, runs the real `_initialize_query_data`, and then runs the real `_register_routes`, which includes Potion.
- Run with `--network none` and dummy environment values.
- Base has 316 rules and trim has 315. The 247 Potion `/api2` rules are identical.
- [`diff`](WP-0d-evidence/routes-base.tsv) shows that the only change is the removal of `/graphql  graphql.graphql  DELETE,GET,POST,PUT`. `/api/timeout  api.timeout_session  POST` is still present in [trim](WP-0d-evidence/routes-trim.tsv).

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
  - 398 modules: 393 OK, and none failed because of a removed package. Output: [`sweep-pipeline-trim.tsv`](WP-0d-evidence/sweep-pipeline-trim.tsv).
  - The 5 failures have nothing to do with this WP. Four modules call Druid at import time and get `ConnectionError` to `druid.invalid`: `config/harmony_demo/database.py`, `config/template/database.py`, `data/pydruid_query/pydruid_query.py` and `data/validation/scripts/validate_pivoted_csv.py`. That is a BE-2 item for WP-4a. The fifth is a mapper ordering error in `data.query.models.query_selections`.
- **Limit.** PyPy resolution of the trimmed files cannot be shown while the pre-existing `cryptography`/`maturin` failure stands. The risk is low: the change only removes requirement lines, and no Python file in the repo imports `fuzzywuzzy`, `jellyfish` or `editdistance` (unit 2).

**Not run.**
- The end-to-end smoke list from `testing.md` (`e2e/`) does not exist yet (WP-2e). In its place: the URL-map diff and the import sweeps above.
- The front-end half (`zen_environment.js`) was not built with `yarn build`. That change is owned by frontend-platform, and WP-0e verifies it.
- Lint and type checks: this branch changes no Python, so ruff and mypy have nothing to check.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
