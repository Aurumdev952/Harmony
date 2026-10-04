---
name: pipeline-contract-oracle
description: How to judge whether tests/pipeline contract/ goldens can be reproduced by a typed Parquet writer (WP-8d); the Druid equivalences the contract must normalise
metadata:
  type: project
---

`tests/pipeline/golden/<case>/contract/` (`druid_rollup.jsonl`, `druid_columns.txt`) is the INV-2 oracle for WP-8d's Polars and Parquet rewrite. Test that it can actually be met:
1. Read `canonical/druid_rows.jsonl`.
2. Explode the collapsed zero rows.
3. Build a Polars frame with explicit dtypes: `val` Float64, strings, list dims.
4. Write it to Parquet, read it back with `to_dicts()`, and feed `contract_rollup` / `contract_columns`.

Use `uv run --no-project --python 3.12 --with polars`. `pipeline_fixtures.py` is stdlib-only, so it imports on 3.12.

**Why:** at 067ec76 (2026-10-04) the contract still keyed on absent vs null, `[x]` vs `x`, and `[]` vs absent. As read back, 14 of 21 flat cases failed. No single dtype for `Sex` fits `wide_multi_value_dimensions` or `handmade_rows_ignore_flags`.

Druid semantics to expect in the contract:
- a missing column equals null;
- `[]` equals null;
- a one-element multi-value equals the scalar;
- multi-value dimensions are stored as `SORTED_ARRAY` by default;
- `''` equals null only under 0.23 legacy null handling. Druid 37 keeps them distinct, so keep `''`.

**How to apply:** in WP-2d follow-ups and in WP-8d review, rerun this round trip before accepting any contract-layer claim. Also check that user-visible side outputs are pinned as interfaces, not as "layout": `metadata_digest_file.csv` is read by `web/client/models/DataDigestApp/IndicatorDigestData.js`.
