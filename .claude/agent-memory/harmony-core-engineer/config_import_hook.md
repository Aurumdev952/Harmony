---
name: config-import-hook
description: Non-obvious semantics of config/__init__.py ConfigImporter (alias config.X to config.<ZEN_ENV>.X) that any change must keep
metadata:
  type: project
---

`ConfigImporter` (rewritten on `find_spec` in WP-3a, 2026-10-04) is appended last to `sys.meta_path`, so `PathFinder` always wins first. That leads to two non-obvious behaviours:
- `config/utils.py` is not whitelisted, but it still loads as itself.
- Submodules of a redirected package (`config.indicator_groups.yellow_fever`) are found through the aliased package's `__path__` and load under the alias name, as a distinct module object from `config.harmony_demo.indicator_groups.yellow_fever`. Pinned in `tests/core/test_config_import_hook.py`.

The alias loader returns the real module from `create_module`. The import system then overwrites `__spec__`, so `exec_module` restores the real spec. Without that, `importlib.reload` would silently stop re-executing the file.

`ZEN_ENV` is read once, when `config` is first imported. `config/loader.py` imports `config.<env>` explicitly and does not use the hook.

`config/<code>/database.py` `DATASOURCE` is a lazy module `__getattr__` (BE-2). `DruidApplicationContext` never used it. The consumers are `data/pydruid_query`, `data/query_policy`, `data/validation`, and one seed script.

**Why:** WP-3b (CPython 3.13) and WP-4a (`harmony.core.deployment`) build on this.
**How to apply:** when replacing it with `harmony.core.deployment` in WP-4a, keep the shared-module-object and reload behaviour, or record the change. Related: [[tooling-traps]].

Since WP-4a (2026-10-05), `config.VALID_MODULES` is `harmony.core.deployment.deployment_codes()`, and `config.loader.import_configuration_module` returns a frozen `Deployment` holding the same module objects. `config/__init__.py` imports `harmony.core.deployment`, so that module must never `import config` at module level. It uses `importlib.util.find_spec('config')` instead.
