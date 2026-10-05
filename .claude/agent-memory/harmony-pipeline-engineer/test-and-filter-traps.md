---
name: test-and-filter-traps
description: How to run pipeline/alert tests and lint, and the SelectorFilter-rejects-None trap when emitting Druid null tests
metadata:
  type: project
---

- `uv run pytest tests/pipeline` fails at conftest (no `hypothesis` in the uv project). Use `CI=1 tests/pipeline/run.sh -q`: it runs on CPython 3.9 with `tests/pipeline/requirements.txt` (130 tests, about 11 s as of 2026-10-04).
- Run `run.sh` from a directory with no `.venv`, for example `cd /tmp && CI=1 <abs>/tests/pipeline/run.sh -q`. `uv run --no-project --with-requirements` still uses the cwd's `.venv`, and any earlier `uv run` in a worktree creates one. Its `pytest_selenium` plugin then fails on `No module named 'py.xml'` before any test runs (2026-10-05).
- Plain `uv run pytest` runs only `tests/golden`. Pass other paths explicitly (`uv run pytest tests/alerts`).
- `data.query.models.query_filter.SelectorFilter` has `value = related.StringField()`, which rejects None. To emit `selector value null` from a QueryFilter list (as in `data/alerts/alert.py`), wrap pydruid in `RawFilter(filter=~Filter(dimension=d, value=None))`. That is core's form from WP-8a N1.
- In SQL-compatible null mode, `not(selector null)` keeps `''` rows. It is correct only because the WP-8a N0 ingest transform stores `''` as null. Keep that in mind for the C-8 Parquet work in WP-8d, see [[wp-8d-parquet-nulls]].
- Lint: `data/alerts/alert.py` is ruff-formatted and S101-clean as of 2026-10-05 (WP-8a pipeline-2). Integration's `ci/lint_python.sh main` applies the full rule set to every file a branch changes, so a touched file must pass `ruff format --check` in full. mypy does not understand `related` models, so it reports `call-arg` errors on every model constructor. Compare error sets before and after a change rather than expecting zero.
