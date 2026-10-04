---
wp: "3a"
title: "Config import hook on `find_spec`"
status: claimed
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

`config/__init__.py` installs `ConfigImporter` on `sys.meta_path`. It redirects `config.<module>` to `config/<ZEN_ENV>/<module>` but implements only the legacy `find_module`/`load_module` protocol. CPython 3.12 removed that protocol, so on 3.12 and later `import config.datatypes` fails with `ModuleNotFoundError`. WP-3b (CPython 3.13 everywhere) waits on this WP.

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Map the hook (`pstack:how`), the whitelist and every importer of `config.*`. Check: findings recorded under Evidence.
2. Failing tests in `tests/core/test_config_import_hook.py`. Check: green on Python 3.9, red on 3.13 for the redirect cases.
3. Rewrite `ConfigImporter` with `find_spec` and `exec_module`, keeping the resolution semantics and Python 3.8 compatibility. Check: the tests pass on 3.8, 3.9 and 3.13.
4. Remove the Druid call that `config/<code>/database.py` makes at import time (phase file 3a, BE-2). Check: a test shows that importing `config.database` makes no Druid call.
5. INV-2: the golden suite and WP-2d's pipeline suite on 3.9 before and after, and the pipeline suite on 3.13 after. Check: 269 passed, `record.py --check` reports 0 drift, and the pipeline results match.
6. Static checks on the touched modules: ruff, black 22.6 `-S -t py39`, mypy.

## Contract changes

None.

## Requests

None.

## Log

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
