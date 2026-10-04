---
name: golden-suite-harness
description: How the WP-2a golden suite boots the legacy query engine offline, and the traps found doing it (hash-seed ordering, Potion bootstrap, uv pip blocked)
metadata:
  type: project
---

These are the non-obvious facts behind `tests/golden/` (WP-2a, branch `mig/WP-2a-golden-query-suite`, 2026-10-04).

- **The environment.** The legacy code runs on host CPython 3.9 through a root `pyproject.toml` with a `golden` dependency group. Run `uv run pytest tests/golden`; no container is needed.
  - `uv pip` is blocked by the modern-python shim, so use `uv sync`.
  - psycopg2-binary 2.8.5 has no cp39 wheel. Use 2.8.6.
  - Shell commands that pipe heredocs into `uv` are refused by the worktree guard. Write a script file and run it.
- **The bootstrap order matters.**
  1. Push an app context carrying `zen_config` first, because `outliers_base.py` reads `current_app` at import time.
  2. Import every `models.alchemy.*` module, because Potion configures all mappers. That import chain needs celery.
  3. Call `GranularityResource.init()` with `app.query_data` set.
  4. Mount `Api(app, prefix='/api2').add_resource(QueryResource)`.
- **Hash-seed nondeterminism.** Druid query JSON depends on `PYTHONHASHSEED` in five places: and/or operands, `in` values, the regex `(a)|(b)` alternation, the aggregator list, and the order of having `havingSpecs`. The suite canonicalises these, and the fake client maps array-result columns by name. Any new canonicalisation must be justified as semantically unordered.
  - **How to apply:** whenever you touch the golden suite, sweep seeds with `for s in $(seq 0 31); do PYTHONHASHSEED=$s uv run pytest tests/golden -q; done`.
- **Verdicts on query-path WPs.** Use in-memory mutants (a pytest plugin that patches functions after collection) rather than editing production files. The ownership hook forbids qa from editing those files.
- **What the frontend actually sends.** A missing filter is serialised as `"filter": {}`, never omitted (omitting it gives HTTP 400). Formula constituents carry no `name` field.
