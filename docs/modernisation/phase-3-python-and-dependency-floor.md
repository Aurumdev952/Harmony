# Phase 3. Python 3.13 and the dependency floor

Back to [overview](overview.md).

**Goal.** Get every Python process onto CPython 3.13 with supported libraries while still on Flask. Phase 4 should only have to change structure, not chase version breakage. The golden, policy and contract suites from phase 2 must stay green after every unit.

## 3a. Replace the config import hook

- **Changes.**
  - Rewrite `config/__init__.py:23-83` as a `MetaPathFinder` that uses `find_spec` and a loader with `exec_module`. Python 3.12 removed the `find_module` and `load_module` fallback it relies on today.
  - Move the Druid call out of `config/<code>/database.py:8` into a function that `DruidApplicationContext` calls lazily.
- **Verification.** Run under Python 3.9 and 3.13: `python -c "import config.general"` with `ZEN_ENV=harmony_demo`, and the full test suite.

## 3b. One interpreter everywhere

- **Changes.**
  - Base every image on `python:3.13-slim-bookworm`, installed with `uv sync --frozen`.
  - Delete the PyPy setup (`SetupEnvForPyPy`, `venv_pypy3`) and every PyPy-only requirement marker and line: the numpy and shapely markers, and the `gspread ... ; platform_python_implementation != 'PyPy'` exclusion WP-0d added (gspread pulls cryptography, which has no PyPy wheel and aborts PyPy on import; under CPython 3.13 the marker simply goes). Pipeline steps run on CPython until phase 8 makes them columnar, and the phase 1 baseline is used to check that the slowdown is acceptable.
  - Lift `numpy` and `shapely` off their PyPy pins.
- **Verification.** Run the pipeline end to end for `harmony_demo` and record the wall-clock time against the PyPy run.

## 3c. SQLAlchemy 1.4 with 2.0 warnings

- **Changes.**
  - Move to SQLAlchemy 1.4 and Flask-SQLAlchemy 2.5 with `SQLALCHEMY_WARN_20=1`.
  - Fix every warning across the about 200 files, using `select()` instead of `Model.query`.
  - Remove the custom `make_declarative_base` override in `db/sqlalchemy.py`.
- **Verification.**
  - The suite passes with warnings set to errors.
  - `flask db upgrade` from an empty database reaches the head of all 143 revisions.

## 3d. Flask 2.3, Werkzeug 2.3, Jinja 3 and the auth libraries

- **Changes.**
  - Replace the private APIs: `werkzeug._reloader` (`web/dev_reloader.py:5`), `werkzeug.cached_property` (`web/server/data/druid_context.py:7`) and `flask._app_ctx_stack` (`data/query/mock/__init__.py:536`).
  - Upgrade flask-jwt-extended to 4: `get_jwt_claims` becomes `get_jwt`, and the claim layout moves from `user_claims` to top-level claims. Existing `accessKey` cookies stay readable through a decoder that accepts both layouts until the longest cookie expires.
  - Upgrade PyJWT to 2 (`web/server/security/jwt_manager.py:82`).
  - Bring flask-login to its current release.
  - Flask-User 0.6 stays until phase 5d removes it. Its reset and invite tokens are pinned by a test.
- **Verification.**
  - The contract suite passes.
  - Log in, log out, reset a password and accept an invite in Playwright.
  - An old-format `accessKey` cookie still authenticates.

## 3e. SQLAlchemy 2

- **Changes.** Move to SQLAlchemy 2.1 and Flask-SQLAlchemy 3.1, and replace sqlalchemy-stubs with the built-in typing.
- **Verification.** Full suite and mypy pass.

## 3f. Replace py77 helpers

- **Changes.**
  - Add `harmony/core/cli.py`, a typer-based `Flags` replacement that keeps flag names.
  - Swap `FileUtils` for `pathlib`.
  - Migrate the 80 importing files by codemod, then remove the `py77` git dependency. Zeus itself keeps running until phase 8. Install it as a vendored CLI if it is still needed then.
- **Verification.** Every script's `--help` output is unchanged in its flags. The pipeline runs end to end.
