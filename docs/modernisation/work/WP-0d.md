---
wp: "0d"
title: "Delete dead backend code and dependencies"
status: building
owner_role: "core"
instances:
  - name: "core-2"
    files:
      - docs/modernisation/work/WP-0d.md
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

## Contract changes

None.

## Requests

Each request is the exact change verified in unit 4. The combined diff was applied to a scratch copy, and its build and sweep results are under Evidence. None of these block a core unit, so this WP's own units continue.

- [ ] **infra**: trim the requirements and the configs that refer to removed packages.
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
- [ ] **lead**: edit `docs/modernisation/phase-0-security-and-subtraction.md` section 0d.
  - Drop "Delete the unused `/api/timeout` route".
  - Replace "Point `zen_environment.js` at the Hasura environment, or delete it" with "Delete it".
  - Note that the Hadoop deletion includes `legacy_task_builder.py` and `scripts/run_indexing.py`.
  - Optional: remove the `#Dask` / `dask-worker-space/` lines from `.gitignore`.

## Log

- 2026-10-04 core-2 unit 1: claimed WP, recorded path ownership; check: `uv run python scripts/agents/ownership.py who <paths>` (table above).
- 2026-10-04 core-2 unit 2: proved targets dead, found `/api/timeout` live; check: `/tmp/wp0d_dead.sh` transcript under Evidence.
- 2026-10-04 core-2 unit 3: wrote per-owner requests; check: each names files, lines and scope.

## Evidence

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

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
