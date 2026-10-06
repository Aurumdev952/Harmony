---
name: test-and-filter-traps
description: How to run pipeline/alert tests and lint, and the SelectorFilter-rejects-None trap when emitting Druid null tests
metadata:
  type: project
---

- Since WP-3b (CPython 3.13 lock, 2026-10-06) the suite runs from the root lock: `CI=true uvx --from uv==0.12.23 uv run --locked pytest tests/pipeline -q` gives 130 passed (without `CI` the property test skips: 129 + 1 skipped). The host uv (0.12.5) fails the lock's `required-version`, hence `uvx --from uv==0.12.23`. `tests/pipeline/run.sh` (3.9 requirements) is the pre-3b path.
- `testpaths = ["tests"]` (pyproject, 2026-10-06), but CI runs each `tests/<dir>` in its own process (`ci/pytest_suites.sh`); pass one suite path at a time.
- `data.query.models.query_filter.SelectorFilter` has `value = related.StringField()`, which rejects None. To emit `selector value null` from a QueryFilter list (as in `data/alerts/alert.py`), wrap pydruid in `RawFilter(filter=~Filter(dimension=d, value=None))`. That is core's form from WP-8a N1.
- In SQL-compatible null mode, `not(selector null)` keeps `''` rows. It is correct only because the WP-8a N0 ingest transform stores `''` as null. Keep that in mind for the C-8 Parquet work in WP-8d, see [[wp-8d-parquet-nulls]].
- Lint: `data/alerts/alert.py` is ruff-formatted and S101-clean as of 2026-10-05 (WP-8a pipeline-2). Integration's `ci/lint_python.sh main` applies the full rule set to every file a branch changes, so a touched file must pass `ruff format --check` in full. mypy does not understand `related` models, so it reports `call-arg` errors on every model constructor. Compare error sets before and after a change rather than expecting zero.
