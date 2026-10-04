---
name: import-hook-review
description: How to review changes to config/__init__.py (ConfigImporter) and lazy module attributes in config/<code>/*.py - old-vs-new probe harness and the import-system edge cases that matter
metadata:
  type: project
---

To review import-hook changes, build two tiny trees in /tmp. Each holds only `config/__init__.py` (old or new), a `config/system.py`, and a synthetic deployment `config/zz/` that contains `general.py`. Add an `a.py` and `b.py` that import each other through `config.a` and `config.b`, a slow module, a module that raises, and a package with relative imports. Run the same probe script under 3.9 (old) and 3.9 plus 3.13 (new), with `PYTHONPATH=<tree>`. The script's directory, not the cwd, is `sys.path[0]`. In a few seconds this compares cycles, thread races, failed targets, reload, `importlib.util.find_spec` and reload after setting `ZEN_ENV`.

**Why:** in the WP-3a review (2026-10-04), the find_spec rewrite matched the old hook in every case except these unset-`ZEN_ENV` ones, which the WP did not list:
- `importlib.util.find_spec('config.X')` now raises instead of returning None.
- `import config` with ZEN_ENV unset, then setting it and calling `reload(config)`, now fails, because the stale None-mode finder sits first.
- `from config import X` still gives "cannot import name". `_handle_fromlist` swallows the ModuleNotFoundError whose `.name` matches.

**How to apply:**
- PEP 562 module `__getattr__`: an exception other than AttributeError propagates through `from m import X`. So code like `try: from config.database import DATASOURCE / except MissingDatasourceException` still catches it.
- An AttributeError raised inside the lookup turns into "ImportError: cannot import name", and `dir()` stops listing the name.
- Check the consumers before calling either of these a defect.
- The built-in `code-review` skill accepts `high <base>...<branch>` plus a checkout path in its args, and runs fine from the reviewer worktree.

Related: [[review-env-traps]], [[worktree-guard-bash]].
