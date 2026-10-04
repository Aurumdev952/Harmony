---
name: test-and-filter-traps
description: How to run pipeline/alert tests and lint, and the SelectorFilter-rejects-None trap when emitting Druid null tests
metadata:
  type: project
---

- `uv run pytest tests/pipeline` fails at conftest (no `hypothesis` in the uv project). Use `CI=1 tests/pipeline/run.sh -q`: it runs on CPython 3.9 with `tests/pipeline/requirements.txt` (130 tests, about 11 s as of 2026-10-04).
- Plain `uv run pytest` runs only `tests/golden`. Pass other paths explicitly (`uv run pytest tests/alerts`).
- `data.query.models.query_filter.SelectorFilter` has `value = related.StringField()`, which rejects None. To emit `selector value null` from a QueryFilter list (as in `data/alerts/alert.py`), wrap pydruid in `RawFilter(filter=~Filter(dimension=d, value=None))`. That is core's form from WP-8a N1.
- In SQL-compatible null mode, `not(selector null)` keeps `''` rows. It is correct only because the WP-8a N0 ingest transform stores `''` as null. Keep that in mind for the C-8 Parquet work in WP-8d, see [[wp-8d-parquet-nulls]].
- Lint baselines: `data/alerts/alert.py` already fails `ruff format --check` on its module docstring, so do not reformat the whole file in an unrelated change. mypy does not understand `related` models, so it reports `call-arg` errors on every model constructor. Compare error sets before and after a change rather than expecting zero.
