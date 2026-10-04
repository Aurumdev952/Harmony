---
wp: "3a"
title: "Config import hook on `find_spec`"
status: review
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
2. **`config.<code>.database.DATASOURCE` is resolved on first access, not on import** (unit 4).
   - A module `__getattr__` calls `DruidMetadata.get_most_recent_datasource(DEPLOYMENT_NAME)` once and caches the result in the module globals.
   - `from config.database import DATASOURCE` and `config.database.DATASOURCE` keep working, and raise the same exceptions (checked against an unreachable Druid: `requests.exceptions.InvalidURL` on import before, the same error on first access after).
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

## Evidence

Logs are under `/tmp/wp3a/` on the build host. Reviewers should rerun the commands below on their own checkout.

- **Golden suite, 3.9 (INV-2).**
  - `uv sync --locked && uv run pytest tests/golden -q`. Before (`mig/integration` `ab4e2f7`): 269 passed (`golden-before.txt`). After the merge: 269 passed (`golden-after-final.txt`).
  - `uv run python tests/golden/record.py --check`. Before and after: `85 cases, 0 fixture files would change`, exit 0 (`record-before.txt`, `record-after-final.txt`).
- **Hook tests.**
  - `uv run -q -p <v> --no-project --with pytest pytest -q -p no:cacheprovider tests/core` gives 16 passed for each `<v>` in 3.8, 3.9, 3.13 and pypy3.9 (`core-*.txt`). 3.11 and 3.12 gave 13 passed at unit 3.
  - QA-1: on `mig/integration`, the redirect cases fail on 3.11 and 3.13, the unset-`ZEN_ENV` case fails on 3.9, and the 3 `database` cases fail on 3.9 (checked there only).
- **Pipeline fixture suite** (WP-2d `1928f7b`, overlaid on `git archive` copies). Run with `CI=1 [PIPELINE_FIXTURE_PYTHON=...] tests/pipeline/run.sh -q`:

  | Interpreter | Before (`mig/integration`) | After (`17a9751`) |
  |---|---|---|
  | 3.9 | 104 passed | 104 passed |
  | pypy3.9 | 104 passed | 104 passed |
  | 3.13 | cannot import `config` (WP-2d README) | collection error in `future==0.18.3`; 104 passed with `future==1.0.0` |
- **Phase check.** `ZEN_ENV=harmony_demo DRUID_HOST=... DEFAULT_SECRET_KEY=... PYTHONPATH=. uv run -p {3.9,3.13} --no-project python -c 'import config.general'` resolves to `config.harmony_demo.general`, with `DEPLOYMENT_NAME == 'harmony_demo'` and the alias set, on both interpreters.
- **No Druid I/O on import.** `/tmp/wp3a/real_database.py` with `DRUID_HOST=http://127.0.0.1:9`:
  - before: `import config.database` raises `InvalidURL`;
  - after: the import succeeds, and the first `DATASOURCE` access raises `InvalidURL`.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-05 qa-3a at 8deaa9f: 16 tests pass on 3.8, 3.9, 3.11, 3.12, 3.13 and PyPy 3.9; 8 fail on 3.13 with the old hook; golden 269 with 0 drift; WP-2d suite (now 130) unchanged on 3.9 and PyPy and passes on 3.13 once future==1.0.0 is substituted; every harmony_demo module resolves identically on 3.9 and 3.13; DATASOURCE lookup lazy (import opens no socket; first read raises the same error); reload semantics kept; web app imports on 3.8. Note: builder's closed-port probe used :9 which never connects (InvalidURL). |
| reviewer | pending | |
| security | n/a | |
