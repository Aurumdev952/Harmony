---
name: full-stack-page-check
description: Why the Flask app cannot be started for page checks without Druid plus ingested demo data, before WP-1d lands
metadata:
  type: project
---

The Flask web app needs a live Druid with at least one datasource at startup: `_create_app_internal` in `web/server/app.py` calls `update_db_datasource` when the `druid_datasource` table is empty, then `initialize_druid_context`. The compose files also publish 80, 443, 6379, 5000 and 8088, which clash with other projects on the dev host.

**Why:** a page check (`verify` on every route) therefore needs Druid, Postgres, Hasura and a `harmony_demo` pipeline run, not just the web image.

**How to apply:** for frontend changes that cannot alter runtime code (dependency removal, comments), prove equivalence by diffing built bundles against `main`. Plan the full page check around the QA harness (WP-2e) or after WP-1d removes Druid from render. See [[local-yarn-build]].

**Template render check instead.** Render every page template with Jinja2 on `main` and on the branch, then `diff -r` the output. Use `ChainableUndefined`; stub `config` (`VENDOR_SCRIPT_PATH`, `IS_PRODUCTION=False`), `sourcemap={}`, `url_for`, `get_flashed_messages`; add the `jinja2.ext.i18n` extension with null translations; put Flask-User 0.6.21's sdist `flask_user/templates` on the loader path. Do not skip `auth/`: `auth/layout.html` extends `layout.html`, so `/user/profile` changes whenever `layout.html` does. A reviewer caught this on WP-0e.
