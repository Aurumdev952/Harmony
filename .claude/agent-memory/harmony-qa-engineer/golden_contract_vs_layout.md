---
name: golden-contract-vs-layout
description: For suites that guard a rewrite (WP-8d Polars), split goldens into a store-level contract and a layout layer, and test the contract against a typed round trip
metadata:
  type: feedback
---

A golden that a rewrite must reproduce has to compare values the way the downstream store sees them, not the way today's writer serialises them. Reviewers rejected WP-2d twice over this:
- Round 1: the contract mixed in the JSON writer's layout (int vs float `val`, list vs string `field`, per-column presence).
- Round 2: the contract told apart values Druid stores identically: a missing column, null and `[]`; `["X"]` and `"X"`; unsorted multi-value lists. `''` stays distinct.

**Why:** a typed Parquet writer cannot reproduce those layout distinctions, so the contract would fail the rewrite for no real change. The reviewer proved it with a Polars to Parquet to `to_dicts()` round trip.

**How to apply:**
- Keep three layers: `contract/` (what the store and the other consumers read), `canonical/` (layout with ordering removed) and `raw/` (bytes).
- Add a test that rebuilds the golden rows as a typed table returns them, and asserts the contract is unchanged.
- Treat files other components read as contract, not intermediates. In WP-2d, `metadata_digest_file.csv` is read by the DataDigest UI and by `populate_pipeline_run_metadata.py`. Grep for consumers before calling an output an intermediate.
- Every completing case should reach the final stage, so that each case pins the contract.
- Kill mutants into the contract layer (`tests/pipeline/mutation_check.py`).
