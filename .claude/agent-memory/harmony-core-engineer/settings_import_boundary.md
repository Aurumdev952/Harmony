---
name: settings-import-boundary
description: Query-engine modules (db.druid.util, data.query.models, query_builder, calendars) must import without config.settings; module-level settings imports break CI
metadata:
  type: project
---

`config/settings.py` raises at import when `DEFAULT_SECRET_KEY` or `DRUID_HOST` is unset. CI's `tests/toolchain/test_locked_environment.py` imports `data.query.models` and `db.druid.query_builder` in a bare environment. Many modules sit below them: `db.druid.util`, the calendar modules and `data.validation.metrics.datatypes`. If any of them gets a module-level `from config import settings`, CI goes red (INV-8).

**Why:** In WP-8a (2026-10-05), b335723 added such an import in `db/druid/aggregations/last_value_aggregation.py`. tests/core sets the env vars with `os.environ.setdefault`, so the core suite stayed green and the bug only showed up in the toolchain suite. Reviewer round 2 rated it High. The fix in 7b22569 moved the import inside the function, and `tests/core/test_import_without_settings.py` now guards it with a subprocess per module.

**How to apply:** In code the query builder reaches, import settings inside the function that reads them. Keep the validation in `config/settings.py` so a bad value still fails at startup (see [[pipeline-builds-flask-app]]). Before you report, run the whole of `ci/pytest_suites.sh`, not only tests/core, tests/druid and tests/golden. When you add a module like this, add it to `MODULES` in that test.
