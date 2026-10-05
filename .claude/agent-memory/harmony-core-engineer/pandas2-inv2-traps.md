---
name: pandas2-inv2-traps
description: pandas 1.5 -> 2.2 behaviour changes that silently alter Harmony query results (row order, dates, to_dict), and how they were pinned in WP-3b
metadata:
  type: project
---

pandas 2.2 changed query output in ways no exception reveals; WP-3b (2026-10-05) found five, fixed in `d9382b0`.

- **Outer merges always sort** (`self.sort = sort or how == "outer"` in pandas/core/reshape/merge.py). `sort=False` is ignored. pandas 1.5 kept first-appearance key order. `db/druid/query_builder.outer_merge_in_appearance_order` restores it; use it for any outer merge whose row order reaches a response.
- `pd.to_datetime(druid_ts, format='%Y-%m-%d')` used to parse full ISO timestamps as UTC; pandas 2 is strict. Use `format='ISO8601'`.
- `df.to_dict('records', SomeDictSubclass)` no longer builds rows through the class.
- Still pending for pandas 3 (FutureWarnings only on 2.2): `fillna` object downcasting in `visualizations/base.py`, lowercase `period_range` freq aliases in `query_builder.py`.

**Why:** golden fixtures were recorded on pandas 1.5.3; any of these drifts is an INV-2 change.

**How to apply:** for any pandas/numpy/Polars bump, diff behaviour against a pre-bump oracle tree, not only golden. See [[differential-oracle-method]].
