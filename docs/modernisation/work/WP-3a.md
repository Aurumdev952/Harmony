---
wp: "3a"
title: "Config import hook on `find_spec`"
status: ready
owner_role: "core"
instances:
  - name: "core-4"
    files: ["config/__init__.py", "config/harmony_demo/database.py", "config/template/database.py", "tests/core/**", "docs/modernisation/work/WP-3a.md"]
branch: "mig/WP-3a-config-import-hook"
requirements: [BE-2, INV-2]
contracts_consumed: []
contracts_changed: []
security_review: false
---

# WP-3a: Config import hook on `find_spec`

`config/__init__.py` installs `ConfigImporter` on `sys.meta_path`. It redirects `config.<module>` to `config/<ZEN_ENV>/<module>` but implemented only the legacy `find_module`/`load_module` protocol. CPython 3.12 removed that protocol, so on 3.12 and later `import config.datatypes` failed with `ModuleNotFoundError`. WP-3b (CPython 3.13 everywhere) waits on this WP.

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Map the hook (`pstack:how`), the whitelist and every importer of `config.*`. Check: findings recorded under Evidence.
2. Failing tests in `tests/core/test_config_import_hook.py`. Check: green on Python 3.9, red on 3.13 for the redirect cases.
3. Rewrite `ConfigImporter` with `find_spec` and `exec_module`, keeping the resolution semantics and Python 3.8 compatibility. Check: the tests pass on 3.8, 3.9 and 3.13.
4. Remove the Druid call that `config/<code>/database.py` makes at import time (phase file 3a, BE-2). Check: a test shows that importing `config.database` makes no Druid call.
5. INV-2: the golden suite and WP-2d's pipeline suite on 3.9 before and after, and the pipeline suite on 3.13 after. Check: 269 passed, `record.py --check` reports 0 drift, and the pipeline results match.
6. Static checks on the touched modules: ruff, black 22.6 `-S -t py39`, mypy.

## How it works now

- **Finder.** `ConfigImporter` is an `importlib.abc.MetaPathFinder`. It is appended last to `sys.meta_path`, as before. For `config.<name>...` whose first segment is not whitelisted, it returns a spec whose `_AliasLoader` does two things:
  - `create_module` imports `config.<ZEN_ENV>.<name>` and returns that module object, so both names map to one module in `sys.modules`, as the old `load_module` arranged.
  - `exec_module` restores the deployment module's own `__spec__`, which `module_from_spec` overwrote. `__name__`, `__file__` and `__spec__.name` stay the real `config.<ZEN_ENV>.<name>`, exactly as on 3.9 before, so `importlib.reload` still re-executes the deployment file in place.
- **Whitelist.** Unchanged: `druid_base`, `system`, `instance`, `locales`, `loader`, `settings` and every deployment directory.
- **Resolution order.** Unchanged. `PathFinder` runs first, so these behaviours are kept and pinned by tests:
  - `config/utils.py` still loads as itself.
  - Submodules of a redirected package (`config.indicator_groups.yellow_fever`) still load under the alias name, through the aliased package's `__path__`.
- **When `ZEN_ENV` is read.** Once, when `config` is first imported, as before. `config.loader.import_configuration_module` imports `config.<env>` explicitly and never used the hook.

### Behaviour changes (for reviewer acceptance)

1. **`ZEN_ENV` unset.**
   - Before: no finder was installed, and `import config.datatypes` failed with `ModuleNotFoundError: No module named 'config.datatypes'`.
   - Now: a finder is installed. It raises a `ModuleNotFoundError` with the same `name`, whose message says that `ZEN_ENV` was not set when `config` was imported and lists the valid values.
   - Explicit (`config.harmony_demo.*`) and whitelisted imports behave as before. The exception type is unchanged.
   - The reviewer found three side effects of installing that finder. I reproduced each on 3.9 with `/tmp/wp3a/unset_probe.py`, against the old and new hook:
     1. `importlib.util.find_spec('config.X')` now raises `ModuleNotFoundError`; before, it returned `None`.
     2. `import config` with `ZEN_ENV` unset, then setting `ZEN_ENV` and calling `importlib.reload(config)`, no longer enables redirects. The finder installed first (unset) raises before the newly appended one is asked. Before, reload appended a working hook.
     3. `from config import X` still fails with the old message, `cannot import name 'X' from 'config'`, not the new one. `_handle_fromlist` swallows a `ModuleNotFoundError` whose `name` is the submodule.
   - No code in the repository calls `find_spec` on `config.*` or reloads `config`. WP-4a replaces this loader with `harmony.core.deployment`.
2. **`config.<code>.database.DATASOURCE` is resolved on first access, not on import** (unit 4).
   - A module `__getattr__` calls `DruidMetadata.get_most_recent_datasource(DEPLOYMENT_NAME)` once and caches the result in the module globals.
   - `from config.database import DATASOURCE` and `config.database.DATASOURCE` keep working, and raise the same exceptions. Checked against a closed port (`DRUID_HOST=http://127.0.0.1`, `:8081` appended, nothing listening): `requests.exceptions.ConnectionError` on import before, the same error on first access after. `MissingDatasourceException` still reaches `query_policy.py`'s `except` (test added).
   - Deviation from the phase file: it says "a function that `DruidApplicationContext` calls lazily", but `DruidApplicationContext` (`web/server/data/druid_context.py`) never reads `config.database`. The consumers are:
     - `data/pydruid_query/pydruid_query.py`, at module level;
     - `data/validation/scripts/validate_pivoted_csv.py`, as an argparse default at module level;
     - `data/query_policy/query_policy.py`, inside a function;
     - `web/server/migrations/seed_scripts/seed_93bb8d693499_add_data_export_field_to_role.py`, inside a function.

     The first two still trigger the lookup when they are imported, which is their own import-time behaviour and unchanged. A lazy attribute kept all four consumers unchanged, including two in lead-owned paths.
3. **Removed module globals.** `config.site_module` and the methods `ConfigImporter.find_module`, `load_module` and `_should_handle_import` are gone. A grep of the repository finds no users.

The invalid-`ZEN_ENV` failure is unchanged: an `AssertionError` with the same message, raised when `config` is imported.

## Contract changes

None.

## Requests

- [ ] infra (WP-2f or WP-3b): run `tests/core` in CI on CPython 3.9 and 3.13 (`uv run -p <v> --no-project --with pytest pytest tests/core`). The root `pyproject.toml` `testpaths` lists only `tests/golden`, so a bare `uv run pytest` skips it. This blocks nothing in this WP.

## Input for WP-3b (found here, not fixed)

- **Pipeline fixture suite on 3.13.** With this branch it imports `config` and gets past the hook. Collection then fails in `related` → `future==0.18.3` → `import imp` (removed in 3.12): `ModuleNotFoundError: No module named 'imp'` (`/tmp/wp3a/pipe-after-3.13.txt`). With `future==1.0.0` substituted in a scratch requirements file, all **104 passed** on 3.13 (`/tmp/wp3a/pipe-313-future1.txt`). `future` is pinned in `tests/pipeline/requirements.txt` and in the root `golden` group.
- **Golden group pins with no CPython 3.13 wheel**, checked per pin with `uv pip install --dry-run --python-version 3.13 --only-binary :all:`:
  - `numpy==1.21.0`;
  - `pandas<2.0`;
  - `psycopg2-binary==2.8.6`;
  - `python-rapidjson==1.9`;
  - `ijson-bigint==3.2.0.post1`;
  - `MarkupSafe==0.23`;
  - `SQLAlchemy==1.3.24`.

  `scipy` resolves. Source builds of the last two were not tried.
- **`requires-python` is `==3.9.*`** in the root `pyproject.toml`, so the golden suite cannot run on 3.13 until WP-3b moves the floor.

## Log

- 2026-10-04 core-4 unit 1: mapped the hook, whitelist, importers, `ZEN_ENV` sources and `DATASOURCE` consumers. `pstack:how` ran inline because the session's limit on concurrent subagents refused its explorer agents. check: probe `/tmp/wp3a/probe.py` on 3.8, 3.9 and 3.13; findings under "How it works now".
- 2026-10-04 core-4 unit 2: `tests/core/test_config_import_hook.py` (13 cases, fresh interpreter per case, `-W error::ImportWarning`). check: 3.8 and 3.9 12 passed, 1 failed (the new unset-`ZEN_ENV` message); 3.11 8 failed (`ImportWarning` from the `find_module` fallback); 3.13 7 failed (redirects).
- 2026-10-04 core-4 unit 3: `ConfigImporter` on `find_spec` plus `_AliasLoader` (`b6cd039`). check: 13 passed on 3.8, 3.9, 3.11, 3.12, 3.13 and pypy3.9; golden 269 passed; `record.py --check` 85 cases, 0 drift; `import config.general` with `ZEN_ENV=harmony_demo` on 3.9 and 3.13.
- 2026-10-04 core-4 unit 4: lazy `DATASOURCE` in `config/harmony_demo/database.py` and `config/template/database.py`, with 3 failing cases first (`on_import: ['harmony_demo']`) (`17a9751`). check: 16 passed on 3.8, 3.9, 3.13 and pypy3.9; golden 269 passed; 0 drift.
- 2026-10-04 core-4 unit 5: pipeline suite (WP-2d at `1928f7b`) before and after. check: 3.9 104 passed both; pypy3.9 104 passed both; 3.13 after: collection error in `future` (WP-3b input).
- 2026-10-04 core-4 unit 6: static checks. check: black 22.6 `-S -t py39 --check`, ruff 0.14 format `--check` (quote-style preserve) and `check --select E4,E7,E9,F` clean on all touched files; mypy 1.3 with `mypy.ini` and `--follow-imports=silent` clean on the 3 modules; `mypy --strict` on `config/__init__.py` clean under 1.3 and current.
- 2026-10-04 core-4: merged `mig/integration` (`d5944d7`); `git ls-files .playwright-mcp` is empty; reran every check on the merge (`ce0a9f8`): golden 269 passed, 0 drift, `tests/core` 16 passed on 3.8, 3.9, 3.13 and pypy3.9.
- 2026-10-05 core-4 review follow-up: listed the reviewer's three unset-`ZEN_ENV` side effects (reproduced); typed the database `__getattr__`; added a test that `MissingDatasourceException` reaches the caller's `except` (`2b90127`). Redid the Druid probe on a real closed port (QA note: `:9` failed URL parsing and never connected). check: `tests/core` 17 passed on 3.8, 3.9, 3.11, 3.12, 3.13 and pypy3.9; black, ruff and mypy clean on touched files.
- 2026-10-05 core-4: merged `mig/integration` (`33f1b72`, now carrying WP-0c, WP-0d and WP-2d); `git ls-files .playwright-mcp` is empty. Reran golden, the pipeline suite (now 130 tests, in-tree) and `tests/core` on the merge; set `status: ready`.

## Evidence

Logs are under `/tmp/wp3a/` on the build host. Reviewers should rerun the commands below on their own checkout.

Final "before" means the merged tree (`33f1b72`) with the three WP-3a production files (`config/__init__.py`, `config/{harmony_demo,template}/database.py`) restored from `ab4e2f7`. Integration already carries an earlier WP-3a merge, so plain `mig/integration` is not a clean "before".

- **Golden suite, 3.9 (INV-2).**
  - `uv sync --locked && uv run pytest tests/golden -q`: before 269 passed, after 269 passed (`golden-final2-before.txt`, `golden-final2.txt`). The first baseline at `ab4e2f7` was also 269.
  - `uv run python tests/golden/record.py --check`: `85 cases, 0 fixture files would change`, exit 0, at `ab4e2f7` and at `33f1b72` (`record-before.txt`, `record-final2.txt`).
- **Hook tests.**
  - `uv run -q -p <v> --no-project --with pytest pytest -q -p no:cacheprovider tests/core` gives 17 passed for each `<v>` in 3.8, 3.9, 3.11, 3.12, 3.13 and pypy3.9 (`core-*.txt`). 3.8 and 3.13 were rerun on `33f1b72`.
  - QA-1: on the old hook, the redirect cases fail on 3.11 and 3.13, the unset-`ZEN_ENV` case fails on 3.9, and the 3 lazy-`database` cases fail on 3.9 (checked there only). The `MissingDatasourceException` case is a regression guard and passes on both.
- **Pipeline fixture suite** (130 tests, in-tree since the merge). Run with `CI=1 [PIPELINE_FIXTURE_PYTHON=...] tests/pipeline/run.sh -q`:

  | Interpreter | Before | After |
  |---|---|---|
  | 3.9 | 130 passed | 130 passed |
  | pypy3.9 | 130 passed | 130 passed |
  | 3.13 | cannot import `config` | 2 collection errors, `No module named 'imp'` from `future==0.18.3`; **130 passed** with `future==1.0.0` |

  Logs: `final-pipe-*.txt`, `final-pipe-313-future1.txt`. Earlier rounds at WP-2d `067ec76` and `1928f7b` gave 104 and 104 on the same interpreters.
- **Phase check.** `ZEN_ENV=harmony_demo DRUID_HOST=... DEFAULT_SECRET_KEY=... PYTHONPATH=. uv run -p {3.9,3.13} --no-project python -c 'import config.general'` resolves to `config.harmony_demo.general`, with `DEPLOYMENT_NAME == 'harmony_demo'` and the alias set, on both interpreters.
- **No Druid I/O on import.** `/tmp/wp3a/real_database.py` with `DRUID_HOST=http://127.0.0.1`; the Druid config appends `:8081`, and nothing listens there (`ss -ltn`):
  - before: `import config.database` raises `requests.exceptions.ConnectionError` (`[Errno 111] Connection refused`);
  - after: the import succeeds, and the first `DATASOURCE` access raises `requests.exceptions.ConnectionError`.
  - QA noted that the first round used `127.0.0.1:9`, which failed URL parsing (`InvalidURL`) and never connected. The conclusion held, and the probe above replaces it.
- **Static checks on touched files.** black 22.6 `-S -t py39 --check`, ruff 0.14 `format --check` and `check --select E4,E7,E9,F` are clean. mypy 1.3 with `mypy.ini` and `--follow-imports=silent` is clean on the 3 modules.
- **Task gate.** `uv run python scripts/agents/task_gate.py WP-3a`:

  ```
  WP-3a meets the definition of done gates
  exit 0
  ```

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-05 qa-3a at 8deaa9f: 16 tests pass on 3.8, 3.9, 3.11, 3.12, 3.13 and PyPy 3.9; 8 fail on 3.13 with the old hook; golden 269 with 0 drift; WP-2d suite (now 130) unchanged on 3.9 and PyPy and passes on 3.13 once future==1.0.0 is substituted; every harmony_demo module resolves identically on 3.9 and 3.13; DATASOURCE lookup lazy (import opens no socket; first read raises the same error); reload semantics kept; web app imports on 3.8. Note: builder's closed-port probe used :9 which never connects (InvalidURL). |
| reviewer | approved | 2026-10-05 rev-3a at 8deaa9f: find_spec rewrite matches the old hook on 3.8-3.13 and PyPy (fake-deployment comparison incl. threads, cycles, reload, failed imports); golden 269 with 0 drift; lazy DATASOURCE keeps every reader's value and exceptions. PR body must list three unlisted unset-ZEN_ENV behaviour changes (find_spec raises; reload after setting ZEN_ENV;  message). Nits: test for the missing-datasource except path; type hints on __getattr__; assert for invalid ZEN_ENV. |
| security | n/a | |
