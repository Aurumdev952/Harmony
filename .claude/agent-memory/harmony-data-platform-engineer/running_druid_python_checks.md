---
name: running-druid-python-checks
description: How to run db/druid and tests/druid checks with uv, which env vars each import needs, and why CI suites must pass with settings unset
metadata:
  type: project
---

Since integration gained `pyproject.toml` and `uv.lock` (2026-10-05), run checks on the host with `uv run pytest ...` and `uv run python`. The old route (mount the worktree into a pipeline image at `/src`) is no longer needed.

- Query-engine modules (`db.druid.util`, `db.druid.query_builder`, `data.query.models`) must import with `DEFAULT_SECRET_KEY`, `DRUID_HOST` and `ZEN_ENV` unset (INV-8, `tests/core/test_import_without_settings.py`). Code that reads `config.settings` imports it inside the function.
- `db.druid.indexing.*` still needs `ZEN_ENV` (it reads `config/<ZEN_ENV>/druid.py`). Tests that import it set the variables with `os.environ.setdefault` at module top.
- Before handing a WP back, run `ci/pytest_suites.sh` with those three variables unset (`env -u ...`). A module-level settings import passed every WP suite but broke `tests/toolchain` in CI (WP-8a round 2, the only High).

**Why:** a test that passes only because a sibling module set the environment first is order-dependent, and reviewers run single files.

**How to apply:** for any WP-8a, 8b or 8c change that touches imports, run the single test file and the full `ci/pytest_suites.sh` with the env unset. See [[worktree-tooling-traps]].
