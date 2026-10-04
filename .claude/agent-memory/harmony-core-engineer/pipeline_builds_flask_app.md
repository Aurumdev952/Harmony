---
name: pipeline-builds-flask-app
description: Pipeline validate steps build a full Flask app via util/local_script_wrapper, so FlaskConfiguration startup checks also hit pipeline runs
metadata:
  type: project
---

The pipeline is not Flask-free. `pipeline/<code>/validate/run/05_populate_unused_fields` and `95_post_actions` call scripts that use `util/local_script_wrapper.local_main_wrapper`. That wrapper calls `create_app(build_flask_config(...))`, so it constructs `FlaskConfiguration` and reads `settings.DEFAULT_SECRET_KEY`. Deployment modules (`config/<code>/general.py`, `druid.py`) and `db/druid/config.py` also import `config.settings`.

**Why:** In WP-0b R1 (2026-10-04) I considered a lazy check at the Flask read. It would have failed pipeline runs after hours of indexing instead of at the start. So the check stayed at import time.

**How to apply:** Put any startup refusal for settings, secrets or config at import or settings load, so it fails fast. Do not put it where Flask reads the value. When you move settings to `harmony.core.settings` (BE-2), keep the pipeline on the same validated load path.
