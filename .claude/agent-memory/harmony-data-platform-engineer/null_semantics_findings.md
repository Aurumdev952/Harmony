---
name: null-semantics-findings
description: What changes in Harmony query results under SQL-compatible nulls and three-valued filters, and the agreed fixes (WP-8a N0-N3)
metadata:
  type: project
---

WP-8a audit (2026-10-04, details and evidence in docs/modernisation/work/WP-8a.md):

- **N0** The pipeline writes `''` for missing location levels; legacy Druid stores it as null, SQL-null Druid keeps `''`. Fixed at ingest: `build_empty_to_null_transforms` in `db/druid/indexing/common.py`. **How to apply:** WP-8c's Parquet/SQL ingestion and contract C-8 must keep "absent dimension = null, never `''`".
- **N1** Builder "no value" tests use `selector value ''`; must be `value null` (core).
- **N2** Druid 28+ three-valued filters: `NOT dim = v` drops null rows that legacy kept (INV-2). Builder makes leaves under `not` two-valued: `and(leaf, not(dim IS NULL))` (core). Also affects exclude_values query policies (INV-3).
- **N3** aggregateLast extension fails under SQL nulls and is 0.23-only; LAST_VALUE needs a native design (core).

- **N3 landed behind a switch.** `HARMONY_DRUID_LAST_VALUE` defaults to `extension`, and `native` (Druid's expression aggregator) is proven equal on 0.23, SQL-null 0.23 and 38. **How to apply:** WP-8b must set `native` as the default, delete the extension branch in `db/druid/aggregations/last_value_aggregation.py` (core), and drop `druid-aggregatable-first-last` from `loadList` and `load_extensions.sh`. Otherwise `calc_last_value` fails on 38.
- **N1b** `data/pydruid_query` (analyst library, no app importers) still defaults to `nation == ''`; outside the golden path, so greps of builder code must include it.
- N2 as landed guards only `selector`/`in`. That is complete because request JSON can carry only selector, in, field, field_in, interval (`__time`) and and/or/not; `RawFilter` is never deserialised.

**Why it matters:** these are the reasons the 8b upgrade cannot just flip versions. Raw Druid 38 hides N1 by accident (unknown under `not` drops the row), so a passing 38 run without N1 is not proof.
