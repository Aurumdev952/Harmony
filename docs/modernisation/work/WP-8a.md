---
wp: "8a"
title: "Remove Druid JavaScript; null-handling audit"
status: review
owner_role: "data-platform"
instances:
  - name: "data-platform-4"
    files: ["druid_setup/**", "db/druid/indexing/**", "scripts/druid/null_audit/**", "tests/druid/**", "docs/modernisation/work/WP-8a.md", "docs/modernisation/work/WP-8a-evidence/**", "docs/modernisation/decisions/*-wp-8a-*.md", ".claude/agent-memory/harmony-data-platform-engineer/**"]
  - name: "core-8a-c"
    files: ["data/query/models/dimension.py", "data/query/models/granularity/**", "db/druid/aggregations/exact_unique_count_aggregation.py", "db/druid/util.py", "db/druid/post_aggregation_builder.py", "db/druid/js_formulas/**", "web/server/data/dimension_metadata_util/compute_sketch_sizes.py", "db/druid/aggregations/last_value_aggregation.py", "tests/core/test_null_selectors.py", "tests/core/test_negation_keeps_nulls.py", "tests/core/test_last_value_native.py", "tests/core/test_policy_exclusion_keeps_nulls.py", "data/query/models/query_filter/query_filter.py", "data/query/models/query_filter/selector_filter.py", "data/query/models/query_filter/in_filter.py", "db/druid/query_builder_util/optimization/filter_optimizations.py", "tests/core/test_empty_value_filters.py", "tests/core/test_exact_unique_count_merge.py", ".claude/agent-memory/harmony-core-engineer/**"]
  - name: "qa-8a"
    files: ["tests/golden/cases/*/druid_query.json", ".claude/agent-memory/harmony-qa-engineer/**"]
  - name: "lead-1"
    files: ["data/pydruid_query/**"]
  - name: "pipeline-8a"
    files: ["data/alerts/alert.py", "tests/alerts/**", ".claude/agent-memory/harmony-pipeline-engineer/**"]
branch: "mig/WP-8a-druid-js-null-audit"
requirements: [SEC-8, DATA-1]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-8a: Remove Druid JavaScript; null-handling audit

SEC-8 needs Druid to run with JavaScript disabled. DATA-1 needs the query builders to give correct results under SQL-compatible null handling, the only null mode in Druid 28 and later (the legacy flags were removed in 32). The builder code that emits JavaScript is owned by core (`data/**`, `db/**`), so this WP proves each native replacement and requests the code change from core. This WP owns the audit tooling and the `druid_setup` flag.

## Plan

Units, in order. Each line names the change and the check that ends it.

1. **Inventory** of every JavaScript construct in the query path, the indexing path and the Druid config, with reachability and owner. Check: the grep below finds nothing outside the list.
2. **Audit harness** (`scripts/druid/null_audit/`): a throwaway Druid per mode (`legacy` = 0.23 as deployed, `sqlnull` = 0.23 with `useDefaultValueForNull=false`, `druid38` = 38.0.0 with JavaScript disabled), a deterministic dataset carrying every null shape the pipeline writes, and `index`, `replay` and `diff` commands that replay every golden case against the live broker. Check: compose validates, the dataset indexes in each mode, and the legacy replay runs all 85 cases.
3. **Native epi week.** Prove a native replacement for the `epi_week_of_year` JavaScript extraction: a pure test over the 400-year Gregorian cycle, and a live run comparing the JavaScript and native extractions on every day from 1900 to 2100 in Druid 0.23, plus the native one on Druid 38 with JavaScript disabled. Request the builder change from core. Check: `uv run pytest tests/druid` and the parity report.
4. **Null audit.** Replay the golden suite on `legacy`, `sqlnull` and `druid38`, list every changed output and decide each one: correct new behaviour, or a builder regression to fix with `COALESCE`/`nvl`/explicit `IS NULL` (never by restoring legacy flags). Check: the decision table below covers every differing case.
5. **Builder fixes** for each regression from unit 4, requested from core with a failing case. Check: the affected cases match `legacy` on `sqlnull` and `druid38`.
6. **Disable JavaScript** in `druid_setup/{single,cluster}/environment/common.env`. Lands with core's unit 3 change. Check: compose validates, and a golden replay on a JavaScript-disabled Druid has no errors.
7. `pstack:interrogate` over the decisions, then review.

## Inventory (unit 1)

Found with `grep -rniE "javascript|js_formula|jsformula"` over `*.py *.env *.json *.properties *.yml *.yaml *.sh`, excluding `web/client`, `docs`, `.claude` and golden fixtures. Template-renderer hits (`javascript_version`) are the web bundle version, not Druid. No JavaScript filter, aggregator or transform exists in indexing (`db/druid/indexing`), the pipeline or the frontend's query serialisation.

| # | Construct | Where | Reachable | Owner | Replacement |
|---|---|---|---|---|---|
| J1 | `JavascriptExtraction(WHO_EPI_WEEK_EXTRACTION_FORMULA)` for the `epi_week_of_year` granularity | `data/query/models/granularity/granularity_extraction.py:32`, formula in `db/druid/js_formulas/week_extraction.py` | yes, wherever an admin enables `epi_week_of_year` in calendar settings (`models/python/config/calendar_settings.py`, stored in Postgres). harmony_demo does not, so no golden case reaches it | core | native `cascade` of `timeFormat` `MM-ww` and an inline `map` lookup (unit 3) |
| J2 | `JSFormula`, `JSPostaggregator`, `RESET_TO_ZERO_FN`, `CDC_EPI_WEEK_EXTRACTION_FORMULA` | `db/druid/js_formulas/base_formula.py`, `week_extraction.py` | no: nothing imports them | core | delete |
| J3 | `'javascript'` branches that rename or collect `fieldNames` of JavaScript post-aggregators | `db/druid/post_aggregation_builder.py:175`, `db/druid/util.py:179` | no: no code emits a JavaScript post-aggregator once J2 goes | core | delete with J2 |
| J4 | `druid_javascript_enabled=true` | `druid_setup/single/environment/common.env:38`, `druid_setup/cluster/environment/common.env:27` | config | data-platform | `false` (unit 6, lands with J1) |

`epi_week` (as opposed to `epi_week_of_year`) already uses Druid's native `week` granularity (`granularity.py:52`).

## Null audit (unit 4)

**Method.** The same deterministic rows (`make_dataset.py`) are indexed into each Druid. Every golden case (85) and five audit-only cases are replayed through the production query path (`tests/golden/harness.run_case`) against the live broker, and each mode's Druid rows and endpoint bodies are diffed against the legacy baseline. Numbers are compared exactly.

The data carries every null shape the pipeline writes:
- `''` for location levels a row lacks;
- absent `Sex` or `Age`, which is a true null;
- unmatched locations;
- zero rows folded into a multi-valued `field`.

The five audit cases (`scripts/druid/null_audit/cases/`) cover shapes the golden catalogue does not reach: a negated filter on a nullable dimension that is not grouped (query filter, calculation filter, `IN`), `COUNT_DISTINCT` over a nullable dimension, and a kept null group.

| Mode | Druid | Nulls | Filters | JavaScript |
|---|---|---|---|---|
| `legacy` | 0.23.0 | legacy (`useDefaultValueForNull=true`) | two-valued | on |
| `sqlnull` | 0.23.0 | SQL-compatible | two-valued (three-valued logic arrived in 28) | on |
| `druid38` | 38.0.0 on Java 21 | SQL-compatible (the only mode since 32) | three-valued | off |

**Results.** Each row counts the cases that differ from legacy 0.23 as deployed.

| Run | Golden (85) | Audit (5) | Evidence |
|---|---|---|---|
| legacy, rerun on a fresh stack | 0 | n/a | [diff-0](WP-8a-evidence/diff-0-legacy-repeat.txt) |
| sqlnull, no fix | 15 | not run | [diff-1](WP-8a-evidence/diff-1-sqlnull-raw.txt) |
| sqlnull + ingest transform | 60 | 4 | [diff-2](WP-8a-evidence/diff-2-sqlnull-transform.txt) |
| sqlnull + ingest transform + builder fixes | 1 (`calc_last_value`) | 0 | [diff-3](WP-8a-evidence/diff-3-sqlnull-transform-candidate.txt) |
| druid38, no fix | 6 | not run | [diff-4](WP-8a-evidence/diff-4-druid38-raw.txt) |
| druid38 + ingest transform | 1 (`calc_last_value`) | 3 (the negated filters) | [diff-5](WP-8a-evidence/diff-5-druid38-transform.txt) |
| druid38 + ingest transform + builder fixes | 1 (`calc_last_value`) | 0 | [diff-6](WP-8a-evidence/diff-6-druid38-transform-candidate.txt) |
| legacy + builder fixes | 0 | 0 | [diff-7](WP-8a-evidence/diff-7-legacy-candidate.txt) |
| legacy + ingest transform | 0 | n/a | [diff-8](WP-8a-evidence/diff-8-legacy-transform.txt) |
| legacy, real builder (659bef9) | 0 | 0 | [diff-9](WP-8a-evidence/diff-9-legacy-real-builder.txt) |
| sqlnull, real builder | 1 (`calc_last_value`) | 0 | [diff-10](WP-8a-evidence/diff-10-sqlnull-real-builder.txt) |
| druid38, real builder | 1 (`calc_last_value`) | 0 | [diff-11](WP-8a-evidence/diff-11-druid38-real-builder.txt) |
| nojs (0.23, legacy nulls, JavaScript off), real builder | 0 | 0 | [diff-12](WP-8a-evidence/diff-12-nojs-real-builder.txt) |
| nojs, final head, LAST_VALUE `extension` (default) | 0 | 0 | [diff-16](WP-8a-evidence/diff-16-nojs-head.txt) |
| sqlnull, final head, `extension` | 1 (`calc_last_value`) | 0 | [diff-17](WP-8a-evidence/diff-17-sqlnull-head.txt) |
| sqlnull, final head, `native` | 0 | 0 | [diff-18](WP-8a-evidence/diff-18-sqlnull-head-native.txt) |
| druid38, final head, `extension` | 1 (`calc_last_value`) | 0 | [diff-19](WP-8a-evidence/diff-19-druid38-head.txt) |
| druid38, final head, `native` | 0 | 0 | [diff-20](WP-8a-evidence/diff-20-druid38-head-native.txt) |
| nojs, real builder + native LAST_VALUE (6d3a35f) | 0 | 0 | [diff-13](WP-8a-evidence/diff-13-nojs-native-last-value.txt) |
| sqlnull, real builder + native LAST_VALUE | 0 | 0 | [diff-14](WP-8a-evidence/diff-14-sqlnull-native-last-value.txt) |
| druid38, real builder + native LAST_VALUE | 0 | 0 | [diff-15](WP-8a-evidence/diff-15-druid38-native-last-value.txt) |

"Builder fixes" are the core requests N1 and N2 below, simulated by `replay --candidate`. The simulation rewrites each posted query at the transport, so it proves the semantics before core lands the code.

The "real builder" rows replay the branch at 659bef9 (N1 and N2 landed, N3 not) with no simulation, all with the ingest transform, on 2026-10-05. They reproduce diff-3, diff-6 and diff-7. In each, 79 or 80 cases differ from the baseline in posted query text only (N1 and N2): Druid rows, bodies and errors are identical. The one exception is `calc_last_value` on the SQL-null modes (N3). `nojs` is what `druid_setup` runs once this WP lands. It matches the legacy real-builder replay case for case (0 differences, query text included). The native epi week on it gives 0 mismatches over 73414 days ([parity-0.23-nojs](WP-8a-evidence/parity-0.23-nojs.txt)), and it refuses the JavaScript extraction (`JavaScript is disabled`).

**Decisions.** Every differing case falls under one of these. None is fixed by restoring legacy flags.

| ID | Change under SQL-compatible nulls | Cases | Decision | Fix |
|---|---|---|---|---|
| N0 | The pipeline's `''` becomes a value of its own, distinct from null, instead of being stored as null. Every "no value" group splits in two (`""` and null), and `''` rows show as `""`. | `dq_data_quality`, `dq_outliers_*`, `group_dimension_include_null`, `table_disaggregated` (raw, both versions) | Regression. Legacy semantics are right for Harmony, where a missing location level means "no value". | Ingest transform `if("<dim>" == '', null, "<dim>")` on every dimension except `field` (`db/druid/indexing/common.py`, this WP). No-op on legacy (diff-8). C-8 (WP-8c) must carry the same rule: Parquet dimensions are null, never `''`. |
| N1 | `selector value ''`, the builder's "has no value" test, matches only `''`, not null. `includeNull: false` groups then keep a null group, and count distinct counts null as a value. | 13 golden cases on sqlnull (the `filter_*`, `group_two_totals`, `hierarchy_*`, `policy_*`, `table_*`, `line_graph_heat_tiles_week` rows in diff-1), 60 once N0 makes the data null; `audit_count_distinct_nullable_dimension` | Regression | Builder emits `selector value null` (core request N1). On 38 three-valued logic happens to hide this, because `not(null = '')` is unknown and the row is dropped. The explicit test is right in both versions. |
| N1c | A stored or submitted filter value `''` (`selector dim ''`, `in [..., '']`) matches only `''`, not null. Stored geo dimension values carry it: `data/query/mock/__init__.py:565-568` (run by `update_db_datasource.py:135`) stores a municipality or region with no parent as `AND(leaf, selector parent '')`, and the client and saved specs send it back unchanged. QA, live: `selector StateName ''` matches 179 rows on legacy and none under SQL nulls; `in [Acre, '']` falls from 4164 to 3985. | `filter_empty_value` (requested from qa below); no existing golden case | Regression | Build time, not a data migration, because it also covers client-submitted and saved specs: `SelectorFilter` and `InFilter` post `''` as `null` (`druid_dimension_value`, core, 1e34633). Stored data is unchanged. See the INV-2 note on `''` filter values. |
| N2 | Three-valued filters (Druid 28+): `NOT dim = v` and `NOT dim IN [...]` drop rows where `dim` is null. Legacy kept them. | `audit_not_selector_query_filter`, `audit_not_selector_calculation_filter`, `audit_not_in_query_filter` on druid38. For example, Acre `yellow_fever_cases` with `NOT Sex = F` falls from 2862.0 to 2656.0. | Regression for INV-2: "everything except females" has always included rows of unknown sex | Builder makes each value comparison under a `not` two-valued: `leaf AND NOT dim IS NULL` (core request N2, landed in 659bef9 in `db/druid/util.py` `_false_on_null`). No-op on 0.23 (diff-7, diff-9). It guards `selector` and `in` leaves, which are the only value leaves a query can carry: the request-deserialisable filters are `selector`, `in`, `field`, `field_in`, `interval` (on `__time`, never null) and `and`/`or`/`not`, and `RawFilter` is built only in code (alerts, data quality), never from request JSON. Leaves testing for null or `''` are left alone, because on legacy Druid they already match null rows. |
| N3 | The Zenysis `aggregateLast` extension throws `NullPointerException` (`DelegateCombingColumnValueSelectorFactory.getLong`) under SQL-compatible nulls. It does not exist for 38. | `calc_last_value` | Regression; also blocks WP-8b | Native LAST_VALUE (core, 4c1b7fe): with `HARMONY_DRUID_LAST_VALUE=native` the wrapper is posted as Druid's built-in `expression` aggregator with the extension's semantics. `extension` stays the default until WP-8b. See the INV-2 note on LAST_VALUE. |

Not observed: aggregate-over-null differences, such as a sum over no rows giving null instead of 0. `DruidQueryClient_` already turns zero-count aggregates into null (the strict-null fields), so bodies match.

**For security review (INV-3).** Exclusions in query policies become `~Filter(type='in', dimension=..., values=[...])` (`web/server/routes/views/query_policy.py:273` and `:302`), which is the native `not(in dim [...])` shape. `audit_not_in_query_filter` proves what Druid 38 does to that exact shape:
- without N2, it also drops rows whose dimension is null, so a policy would hide more than it does today;
- with N2, it matches legacy (diff-5 against diff-6).

So N2 keeps policy decisions identical. Without N2 they would only become more restrictive, never less.

`tests/core/test_policy_exclusion_keeps_nulls.py` (6d3a35f) pins N2's final form on the policy path end to end. A caller whose `QueryNeed` excludes a value posts real endpoint requests through `AuthorizedQueryClient`. Every posted filter must hold the exclusion as `not(and(in dim [v], not(dim IS NULL)))` and never as the bare `not(in)`. It covers:
- a hierarchical dimension (`StateName`, `_construct_hierarchical_filter`) and a simple one (`source`, `_construct_single_filter`), each on `calc_last_value` and `calc_count_distinct_by_state`;
- the exact COUNT_DISTINCT inner query, which `run_query` builds from the policy-ANDed `dimension_filter`. No golden case reaches it (harmony_demo's sketch sizes pick thetaSketch).

All five cases fail with the N2 rewrite removed. The test does not decide reachability: whether a live identity reaches the exclusion branch is still for `tests/authz`.

Reachability: I could not reach the exclusion from a JWT identity. The token and account intersection removes it, as `policy_jwt_exclude_values` pins. An audit case built for this (account with all states, token excluding Pará) posted only `source in [yellow_fever]`. Whether any live identity reaches the exclusion branch is for the policy suite (`tests/authz`).

## INV-2 note: golden fixtures (N1 and N2)

- **Cases:** the 76 golden cases whose `test_druid_queries` fails at 659bef9 (`uv run pytest tests/golden`: 76 failed, 210 passed, all failures are posted-query checks). Only their `druid_query.json` changes. No `expected_response.json` and no `druid_response.json` changes.
- **Before and after.**
  - N1, in all 76: the builder's "has no value" test. For example, `calc_count_distinct_by_state`:
    ```diff
    -{"field": {"dimension": "StateName", "type": "selector", "value": ""}, "type": "not"}
    +{"field": {"dimension": "StateName", "type": "selector", "value": null}, "type": "not"}
    ```
  - N2, also in `filter_not` and `filter_nested`, the only golden cases with a negated value filter. For example, `filter_not` (`NOT (Death = 1 OR no state)`, both changes):
    ```diff
    -{"type": "not", "field": {"type": "or", "fields": [
    -  {"type": "selector", "dimension": "Death", "value": "1"},
    -  {"type": "selector", "dimension": "StateName", "value": ""}]}}
    +{"type": "not", "field": {"type": "or", "fields": [
    +  {"type": "and", "fields": [
    +    {"type": "selector", "dimension": "Death", "value": "1"},
    +    {"type": "not", "field": {"type": "selector", "dimension": "Death", "value": null}}]},
    +  {"type": "selector", "dimension": "StateName", "value": null}]}}
    ```
- **Proof:**
  - `uv run python scripts/druid/null_audit/check_fixture_drift.py` replays every case with its recorded Druid responses. Against the fixtures before qa's regeneration (b84e9e9) it printed `76 cases post changed queries; 0 other differences`. Since the regeneration (c9f7d8e) it prints `0 cases post changed queries; 0 other differences`. It compares the posted queries against the fixtures rewritten by an independent statement of N1 and N2, and every body against `expected_response.json`.
  - Live, with the real builder at 659bef9 and no simulation (diff-9 to diff-12):
    - 0 differences in Druid rows, bodies or errors on legacy 0.23 and on `nojs`;
    - on 0.23 with SQL-compatible nulls and on 38, only `calc_last_value` (N3).
- **Why it is correct.**
  - N1: on Druid 0.23 with legacy nulls, `selector value null` and `selector value ''` match the same rows, because `''` is stored as null (diff-7). Under SQL-compatible nulls, only `value null` matches a missing value.
  - N2: on 0.23, `NOT dim IS NULL` is true on every row that `dim = v` matches, so `and` returns the bare leaf. On 28 and later it turns "unknown" into "false" on null rows, so `not` keeps them as legacy did (diff-5 against diff-6).

## INV-2 note: `''` filter values (N1c)

- **What changes.** Only the posted query, and only for a filter whose value is `''`. `SelectorFilter(dim, '')` posts `selector dim null`, and `InFilter(dim, [v, ''])` posts `in dim [v, null]`. The request, the stored filters and the cache key (request JSON) are unchanged. No existing golden case carries `''` (`record.py --check`: 85 cases, 0 fixture files would change).
- **Before and after**, for the stored shape of a municipality whose state is unknown:
  ```diff
  -{"type": "and", "fields": [{"type": "selector", "dimension": "MunicipalityName", "value": "Rio Branco"}, {"type": "selector", "dimension": "StateName", "value": ""}]}
  +{"type": "and", "fields": [{"type": "selector", "dimension": "MunicipalityName", "value": "Rio Branco"}, {"type": "selector", "dimension": "StateName", "value": null}]}
  ```
- **Why it is correct.**
  - On legacy Druid, `''` is stored as null, so `value ''` and `value null` match the same rows (the N1 argument, diff-7). With N0 the data is null in every mode, and only `value null` matches it under SQL nulls.
  - `in` with `null` in `values` matches null rows. The Druid filter docs (latest, checked 2026-10-05) say: "If the `values` array contains `null`, the "in" filter matches null values." In 0.23.0, `InDimFilter` keeps a `null` in its value set (under legacy nulls it also turns `''` into null), and its string predicate is `values::contains`, which matches a null row when the set holds null (source read 2026-10-05). The live replay requested below confirms it per mode.
  - Under `not`, N2 leaves these leaves alone, as before: `_false_on_null` skips a leaf holding `null` or `''`. A null test is never unknown, so `not(selector dim null)` and `not(in dim [v, null])` exclude the null rows on 38, as legacy did.
- **Knock-on fixes in the same commit**, because a built filter can now hold `null` where it held `''`:
  - `build_query_filter_from_aggregations` (`db/druid/util.py`): a calculation filter on `''` used to crash `get_dimension_filters` (`set.update(None)`) and `sorted()` (None against str). It now collects `null` and sorts it first, which is the position `''` had.
  - The optimizer's dedupe hash (`filter_optimizations.hash_simple_filter`) hashes values as JSON. Before, `selector dim null` and `selector dim 'None'` hashed equal, and one of the two was dropped from an `and`/`or`. That collision has existed since N1. The hash only decides dedupe, so no posted query changes.
- **Proof.**
  - Offline: `tests/core/test_empty_value_filters.py`, 9 tests (8 fail before 1e34633). They cover the selector, the `in`, the stored geo value through `DimensionValueFilterItem`, the negated forms, the optimizer, and the pushdown.
  - Golden case `filter_empty_value` (requested from qa below), recorded in a scratch copy: it posts `null` for all three `''`. Its body keeps the Acre row with no municipality, which only `in [Belém, '']` reaches. With the translation removed, `test_druid_queries` fails and the body still matches, because synth answers like legacy 0.23. `uv run pytest tests/golden` 272 passed with it; `record.py --check` 86 cases, 0 changes.
  - Live, across modes: requested from data-platform below. Expected: 0 result differences against legacy on `nojs`, `sqlnull` and `druid38`, and differences with integration code on the SQL-null modes.

## INV-2 note: LAST_VALUE (N3)

**What changes.** With `HARMONY_DRUID_LAST_VALUE=native`, `db/druid/util.py` builds the `aggregateLast` wrapper as a Druid `expression` aggregator (`db/druid/aggregations/last_value_aggregation.py`). The rewrite happens where pydruid assigns aggregator names, so the combine expression uses the posted name even after `ComplexCalculation` re-keys a calculation. It covers both LAST_VALUE classes: the query model and the deployment aggregation rules.
- The accumulator is `[timestamp, value]`.
- Fold: a later row replaces the accumulator; a row at the same time is combined with the inner sum, max or min.
- Combine: segment partials merge the same way.
- Finalize: returns the value.

The default stays `extension`, so deployments on 0.23 post exactly what they post today: `calc_last_value`'s `druid_query.json` is unchanged and needs no regeneration. WP-8b sets `native` everywhere, deletes the `extension` branch, and drops `druid-aggregatable-first-last` from `loadList`. Until then, a deployment that turns on SQL-compatible nulls must also set `native`.

**Semantics, extension against native.** Every row is "same" unless it says otherwise.

| Aspect | Extension (0.23, legacy nulls) | Native | Evidence |
|---|---|---|---|
| Time ordering | Raw `__time` of each row, per result row (dimensions and granularity bucket), only among rows that pass the aggregator's filter | Same: `cast("__time", 'DOUBLE')` is exact for epoch milliseconds below 2^53 | live reference test, 5 granularities, 2 intervals |
| Ties at the latest time | Inner aggregator applied to every tied row | Same: combined with `+`, `greatest` or `least` | live: shapes with tied rows exist (asserted); a mutation that keeps one tied row fails (1.0 against 122.0) |
| Earlier rows in the bucket | Ignored | Same | live: buckets with more than one time exist (asserted) |
| Merging segments | Later partial wins; equal times combine | Same; empty partials are skipped (`shouldCombineAggregateNullInputs: false`) | granularity `all` across 2018 to 2025 month segments |
| Null metric on a row | Read as 0 (legacy) | `nvl(metric, 0.0)`: read as 0 in every null mode. Under SQL-compatible nulls the extension throws instead, and `doubleSum` would skip the null. Unreachable today: the rollup metrics `sum`, `count`, `min`, `max` are never null. | design |
| No matching rows in a result row | 0, which the client turns into null through `__count` (SUM, MAX, MIN). COUNT has no `__count`, so it stays 0. | 0 in every null mode (`isNullUnlessAggregated: false`), so the bodies are the same | live: `test_native_last_value_with_no_rows_is_legacy_zero`, 4 operations, 3 modes |
| MAX/MIN with no rows | -Infinity/+Infinity before the client nulls it | 0 before the client nulls it | not visible: masked by `__count` |
| AVERAGE | Ratio of the last sum to the last count | Same; the post-aggregator reads finalized values | live, 2 intervals, 2 granularities |

No row needed an options decision: the extension's semantics are preserved exactly.

**Proof.**
- `tests/core/test_last_value_native.py`: 11 offline tests pin the posted aggregator for every operation, the re-keyed name, the config aggregation rule, identifier quoting, the `extension` default (equal to the golden fixture) and rejection of unknown settings. Without the build hook, 8 of 11 fail.
- `tests/druid/test_last_value_live.py`, on all three audit stacks: [n3-last-value-live](WP-8a-evidence/n3-last-value-live.txt), 20 passed.
  - The production builder's native query equals a reference built from core aggregators only (group by exact `__time`, take the latest per group client-side) on 100 shapes per stack: SUM, COUNT, MAX and MIN × 2 intervals × 5 granularities × 5 groupings, including nullable `Sex` and `Age`.
  - On `nojs` (0.23, legacy nulls), native and extension return identical rows on all 100 shapes.
- Golden and audit replay with native on: diff-13 to diff-15. 0 differences in Druid rows, bodies or errors on all three modes; 80 cases differ in query text only. On each mode, `calc_last_value`'s Druid response and body equal the legacy 0.23 baseline (`legacy2`, which ran the extension).

## Interrogation (unit 7)

The `pstack:interrogate` model panel (three reviewers) could not start on 2026-10-05: the session's subagent cap (20 concurrent) was reached. The filled prompt, with intent, scope (the WP-8a commits only) and six focus questions, is ready for the lead to dispatch. Until then, this is the lead pass over the same questions, with the paths traced:

- **N2 completeness: holds.** Every native `not` the app posts is built by pydruid's `Filter.build_filter` (query filter in `pydruid/query.py:272`, filtered aggregators in `pydruid/utils/aggregators.py:79`), which `db/druid/util.py` replaces. This covers the optimiser's merged NOTs (`filter_optimizations.py:141,191,196`) and policy exclusions (`query_policy.py:273,302`). The two raw-dict `not` filters (`compute_sketch_sizes.py:126`, and the null guard in `_false_on_null` itself) negate null tests, which need no guard. Double negation matches legacy: on a null row, the inner `and` is false, so `not(not(.))` is false, as on legacy.
- **extractionFn on the null test: right.** Three-valued "unknown" comes from the extraction's output being null, so the guard must test that output, not the raw column.
- **INV-3: holds.** On 0.23 the guard is the identity (diff-7, diff-9, diff-12). On 28 and later it can only re-admit rows whose dimension is null, which legacy admitted, so no policy returns more rows than it does today.
- **N0 coverage: holds** for every ingested dimension. `UNFILTERABLE_DIMENSIONS` is a subset of `DIMENSIONS` (`task_runner_util.build_dimension_spec_dimensions`), and `field`, the only multi-valued dimension, is excluded. Compaction re-reads stored nulls.
- **Act on (request below): N1 missed `data/pydruid_query/pydruid_query.py`.** `DEFAULT_FILTER = Dimension('nation') == ''` (line 23) and the documented `{'nation': ['']}` selection are "has no value" tests. On SQL-null Druid they match no row once N0 stores null. No app module imports this analyst library, so no golden case or endpoint changes, but DATA-1 covers every query builder.
- **Consider (question for review): a stored filter whose selected value is `''`.** On legacy, `in [..., '']` also matches null rows; on SQL-null Druid it matches nothing. No golden case does this, and I could not establish whether the dimension-value picker can produce `''`. QA or core to confirm or add a case.

## Contract changes

None. Note for WP-8c (C-8 owner is this role): the Parquet ingest schema must state that dimension values are null when absent, never `''` (N0).

## Requests

- [x] core: replace J1 with the native extraction (blocks unit 6). Landed in c808afa, merged; strict xfail removed, `tests/druid` 11 passed. In `GranularityExtraction.EXTRACTION_MAP`, set `'epi_week_of_year'` to `CascadeExtraction([TimeFormatExtraction('MM-ww', 'en', 'UTC'), MapLookupExtraction(EPI_WEEK_OF_YEAR_MAP)])`. This needs a small `CascadeExtraction` (`{'type': 'cascade', 'extractionFns': [fn.build() ...]}`), because pydruid has none. The 75-entry map is `tests/druid/epi_week.epi_week_map()`; commit it as a literal next to the extraction. The built dict must equal `epi_week_of_year_extraction()`. Remove the `xfail` marker on `test_builder_emits_the_native_extraction` in the same commit: it is strict, so it fails the day the builder matches. Delete J2 (`db/druid/js_formulas/`) and the J3 branches. Proof that the change is safe: unit 3 evidence. No golden case changes, because harmony_demo does not enable the granularity.
- [x] core (N1, blocks unit 5): landed in b366263..c808afa, merged. The "has no value" test becomes `selector value null` instead of `''`. Sites: `data/query/models/dimension.py:45` (`DimensionFilter(...) != ''`), `db/druid/aggregations/exact_unique_count_aggregation.py:70`, `web/server/data/dimension_metadata_util/compute_sketch_sizes.py:130`. Only the posted queries change (`druid_query.json`); every `expected_response.json` stays byte-identical on legacy (diff-7).
- [x] qa (blocks review): regenerated 2026-10-05 by qa on `mig/WP-8a-druid-js-null-audit-qa` (see the qa log line). Regenerate `druid_query.json` for the 76 cases in the INV-2 note (`uv run python tests/golden/record.py <cases>`, list from `record.py --check`) on this branch. N2's final form (659bef9) is confirmed by the 2026-10-05 live replays (diff-9 to diff-12), so this is unblocked. N3 must not change any other case's query; if it does, regenerate those too. Check: before regenerating, `check_fixture_drift.py` reports `76 cases post changed queries; 0 other differences`; after, `uv run pytest tests/golden` is green.
- [x] pipeline (N1): the same change in `data/alerts/alert.py:96` (`NotFilter(SelectorFilter(..., value=''))`). Done 2026-10-04 on `mig/WP-8a-druid-js-null-audit-pipeline`: the guard is now core's form, `~Filter(dimension=..., value=None)` (5b12e5f on `mig/WP-8a-druid-js-null-audit-core`), wrapped in `RawFilter` because the `SelectorFilter` model's `value` is a required `StringField` and rejects None. Relies on N0: under SQL-compatible nulls, `not(selector null)` keeps `''` rows, so it is right only while ingest stores `''` as null.
- [x] core (N2, blocks unit 5): landed in 659bef9 and merged. Inside a negated filter, emit each value comparison as `and(leaf, not(selector dim null))`. Core guards `selector` and `in`, the only value leaves a query can carry (see N2 in the decision table), not the `bound`/`regex`/`search`/`like` this request also listed. Check passed: the three `audit_not_*` cases match legacy on druid38 with the real builder (diff-11).
- [x] core (N3, blocks unit 5 and WP-8b): a native LAST_VALUE that aggregates exactly the rows at the largest timestamp per group, ties included, without the `aggregateLast` extension. Landed in 4c1b7fe on `mig/WP-8a-druid-js-null-audit-core` (core-8a-c, 2026-10-05). The check passed with native on: `calc_last_value` matches legacy on sqlnull and druid38 (diff-14, diff-15), and native equals the extension on 0.23 with legacy nulls (nojs, 100 shapes, and diff-13). Semantics in the INV-2 note on LAST_VALUE. The default stays `extension` until WP-8b, which must set `native`, delete the extension branch and drop the extension from `loadList`. It does not change any other case's posted query, so the qa regeneration list stays at 76.
- [ ] pipeline (from the qa review, blocks `ready`): `data/alerts/alert.py:198` is `assert False, f'Time granularity: {time_granularity} is not supported'`. Integration's `ci/lint_python.sh` rejects it (S101) because the file changed on this branch, and under `python -O` it vanishes and the function falls through. Replace it with `raise ValueError(...)`, with a test for an unsupported granularity. Check: `ci/lint_python.sh main` is clean for `alert.py` after integration is merged, and `tests/alerts` passes.
- [x] lead (gate): solved on integration by e86d91a (a `lead-1` instance may claim paths with no ownership row); clears once integration is merged, and the instance is renamed `lead-1`. Original: `task_gate.py WP-8a` reports `data/pydruid_query/pydruid_query.py (owner: lead)` under "files outside the owner role". The path matches no ownership row, and the gate's role list has no `lead`, so no front-matter entry can clear it. Add an ownership row, or record the gate exception. Data-platform does not edit `scripts/agents/`.
- [x] lead (N1b, from unit 7; reassigned from core): done in 3953bee, where the lead deleted `data/pydruid_query`; the `lead` instance in the front matter claims it. `data/pydruid_query/**` matches no ownership row, so it is the lead's (SPEC section 6) and the core hook refuses the edit. Recommendation: delete the module rather than fix it. Nothing imports it: a grep over every file type finds only the module-name entry in `tests/web/test_no_raw_queries_from_routes.py` and that test's synthetic source text, both harmless after deletion. It also cannot be imported without `DRUID_HOST` (WP-0d sweep, WP-3a). If it is kept instead, apply the original request: `DEFAULT_FILTER = Dimension('nation') == None`, the `{'nation': ['']}` docstring example, and a test that the default serialises as `selector value null`.
- [x] data-platform (from qa, does not block): fixed 2026-10-05. The rewrite now skips an `and` that already is `[leaf, not(selector dim null)]`, in either operand order. Check: on the regenerated fixtures it prints `0 cases post changed queries; 0 other differences`. For all 85 fixtures, `rewrite(fixture at b84e9e9) == regenerated fixture == rewrite(regenerated fixture)` as canonical queries. Original report: `check_fixture_drift.py` is not idempotent. After the regeneration it prints `filter_nested` and `filter_not: queries differ beyond the accepted changes` and `0 cases post changed queries; 2 other differences`, and exits 1. The cause is that `_guard_leaves` recurses into an `and` that is already `[leaf, not(selector dim null)]` and guards the leaf a second time. Posted queries equal the fixtures in all 85 cases, and no body differs. Either skip already-guarded `and` nodes, or record that the tool applies only to pre-N2 fixtures.
- [ ] lead: dispatch the `pstack:interrogate` panel (claude-opus-5, claude-fable-5, claude-sonnet-5), which the subagent cap blocked, with the prompt in the Interrogation section's scope.
- [x] qa or core (from unit 7): can a saved query or dashboard filter carry `''` as a selected dimension value? If yes, add a golden case and decide it as N1. Answered yes by qa's verdict: stored geo dimension values carry `''` for a missing parent. Decided as N1c and fixed at build time (core-8a-c, 1e34633). The golden case is the qa request below.
  - Core's answer from the server side (core-8a-c, 2026-10-05): not through the product. The filter picker's values come from `DimensionValuesLookup.load_dimensions_from_druid` (`web/server/data/dimension_values.py:61`), which queries with `Dimension(d) != None`. On legacy Druid `''` is null, and with N0 it is stored as null, so `''` is never offered. A stored `QueryPolicy` with `dimension_value=''` has no include values and no all-values flag, so it falls to `Dimension(d) == NO_FILTER_VAL` (deny) in every null mode.
  - Only a hand-written or API-posted spec could carry `''`, and on SQL-null Druid that would match nothing. Left open for qa to confirm on the client: free-text or pasted filter values, and saved specs created before N0.
- [ ] qa (N1c, blocks review; core cannot write `tests/golden/cases/**`): add the golden case `filter_empty_value`, then `uv run python tests/golden/record.py filter_empty_value` on a branch that has 1e34633. Check: `record.py --check` gives 86 cases and 0 changes, and `uv run pytest tests/golden` passes. Core recorded it in a scratch copy: posted filter has `null` in all three places, and the body has two rows (Acre with no municipality, Belém 336.0).
  - `case.json`: `{"description": "Stored dimension values that write a missing value as '': a municipality with no state (AND with StateName ''), an IN holding '', and the negated geo value. '' is posted as null.", "endpoint": "table", "policy": null}`
  - `request.json`: `{"fields": [{"id": "yellow_fever_cases", "calculation": {"type": "SUM", "filter": {"type": "FIELD", "fieldId": "yellow_fever_cases"}}}], "filter": {"type": "AND", "fields": [{"type": "INTERVAL", "start": "2024-01-01", "end": "2024-04-01"}, {"type": "OR", "fields": [{"type": "AND", "fields": [{"type": "SELECTOR", "dimension": "MunicipalityName", "value": "Rio Branco"}, {"type": "SELECTOR", "dimension": "StateName", "value": ""}]}, {"type": "IN", "dimension": "MunicipalityName", "values": ["Belém", ""]}]}, {"type": "NOT", "field": {"type": "AND", "fields": [{"type": "SELECTOR", "dimension": "MunicipalityName", "value": "Cruzeiro do Sul"}, {"type": "SELECTOR", "dimension": "StateName", "value": ""}]}}]}, "groups": [{"dimension": "StateName", "includeAll": false, "includeNull": true, "includeTotal": false}, {"dimension": "MunicipalityName", "includeAll": false, "includeNull": true, "includeTotal": false}], "type": "GROUP_BY"}`
- [ ] data-platform (N1c, blocks review; the stacks are down): replay `filter_empty_value` and QA's two live shapes (`selector StateName ''`, and `in StateName [Acre, '']`, as audit cases) on `legacy`, `nojs`, `sqlnull` and `druid38` with the ingest transform. Use core's head (below) and integration code. Check: with core's head, 0 differences in Druid rows and bodies against the legacy baseline in every mode (179 rows and 4164 on SQL nulls). With integration code, the SQL-null modes differ, which shows the case is not vacuous.
- [ ] data-platform (N3, after 5a0ece3): rerun `tests/druid/test_last_value_live.py` with `HARMONY_DRUID_LAST_VALUE=native` on `nojs`, `sqlnull` and `druid38`. The native aggregator now posts `accumulatorIdentifier` (security low item 1). Druid 0.23.0's `ExpressionLambdaAggregatorFactory` takes this property, default `__acc` (source read 2026-10-05). The value is unchanged for every real name, so only the posted text changes. Check: 20 passed per stack.
- [ ] data-platform (security low item 2, from the lead 2026-10-05; the ownership hook refuses core): in `db/druid/indexing/common.py:31`, quote the dimension in the ingest expression with `json.dumps(dimension)`, as `last_value_aggregation._identifier` does. Hardening only: dimensions come from config. Plain names post the same text.
- [ ] core follow-up for WP-1c/WP-4d (from security, not this WP): the exact COUNT_DISTINCT inner query computes `<agg> / <agg>` (`exact_unique_count_aggregation._HelperCalculation`, the `const_formula`). That divides by zero when an inner group's filtered count is 0. This predates WP-8a and happens on 0.23 and 38.
- [x] qa-1a (WP-1a): use of host Druid. Answered by the lead 2026-10-04: WP-1a's `harmony-wp1a-perf-druid` may be used read-only. Not needed. Every WP-8a run uses its own throwaway projects `wp8a-legacy`, `wp8a-sqlnull` and `wp8a-druid38` (ports 58891 to 58893, loopback only, metadata on tmpfs). No WP-8a run touched WP-1a's project.

## Log

- 2026-10-04 data-platform-3 unit 1: inventory above; check: the grep finds nothing outside J1 to J4.
- 2026-10-04 data-platform-3 unit 2: audit harness (`scripts/druid/null_audit/`); check: compose validates per mode, the dataset indexes (9475 input rows, 9459 after rollup), and the legacy replay runs 85 of 85 cases with 0 errors (4 return no rows on purpose: `calc_formula_invalid`, `policy_none`, `policy_source_only`, `policy_jwt_exclude_values`).
- 2026-10-04 data-platform-3 unit 3: native epi week proven; check: `uv run pytest tests/druid` 9 passed, 1 strict xfail (the builder still emits JavaScript, pending the core request); live parity on 0.23 legacy and 0.23 SQL-compatible nulls: 73414 days 1900-01-01..2100-12-31, 0 mismatches between native, JavaScript and the Python port.
- 2026-10-04 data-platform-3 unit 4: null audit and the N0 ingest transform; check: decision table above covers every differing case of 9 runs; `uv run pytest tests/druid` 10 passed, 1 strict xfail; native epi week on druid38 with JavaScript off: 0 mismatches.
- 2026-10-04 data-platform-3 unit 6 (part 1): `druid_javascript_enabled=false` in `druid_setup/{single,cluster}`; check: all four compose files validate (`docker compose ... config --quiet`); the JavaScript-disabled Druid 38 refuses a JavaScript extraction (`IllegalStateException: JavaScript is disabled`). Still to do: a replay on mode `nojs` (0.23, legacy nulls, JavaScript off, which is what `druid_setup` runs after this WP), and the core J1 change must land before this WP merges, or `epi_week_of_year` breaks.
- 2026-10-04 pipeline (supporting) N1 in alerts: `data/alerts/alert.py` guard tests `selector value null`; check: `tests/alerts/test_alert_null_guard.py` failed first (2 of 6: the posted filter, and null rows let through on sqlnull), then 6 passed. It pins the posted filter and its kept rows on legacy, sqlnull and druid38, and that legacy keeps the same rows as with `value ''`. `tests/pipeline/run.sh` 130 passed, `uv run pytest` (golden) 269 passed, ruff check clean, black and ruff format clean on the new test, mypy shows the same 9 pre-existing `related` errors in `alert.py` before and after.

- 2026-10-05 data-platform-4 resumed from data-platform-3 (host reboot), branch at 659bef9. The strict xfail on `test_builder_emits_the_native_extraction` was already removed by core in c808afa. `uv run pytest tests/druid` 11 passed, no markers.
- 2026-10-05 data-platform-4 drift check covers N2: `check_fixture_drift.py` rewrites fixtures by an independent statement of N1 and N2, and `run_audit.py diff` separates query-text-only cases from result changes; check: `76 cases post changed queries; 0 other differences`, ruff (pyflakes) clean.
- 2026-10-05 data-platform-4 unit 5/6 live replays with the real builder (659bef9) on fresh `legacy`, `nojs`, `sqlnull` and `druid38` stacks (ports 58891 to 58893, dataset sha256 35af2e55…c81c regenerated and identical, 9459 rows after rollup in each); check: 0 result differences on legacy and nojs; only `calc_last_value` (N3) on sqlnull and druid38; nojs native epi week parity 0 mismatches over 73414 days; nojs refuses JavaScript. `uv run pytest tests/golden tests/druid tests/alerts`: 210 passed, 76 failed, all posted-query fixture checks pending the qa regeneration.
- 2026-10-05 data-platform-4 unit 7 (lead pass): interrogation section above. The model panel is blocked by the subagent cap and requested from the lead. One act-on finding (N1b, core request), one question for review. Status set to review as the lead directed. These remain open and must close before `ready`: N3 (core-8a-c), N1b (core), the qa fixture regeneration, and the panel.
- 2026-10-05 qa (supporting, `mig/WP-8a-druid-js-null-audit-qa` from b84e9e9) fixture regeneration for N1 and N2. Before: `check_fixture_drift.py` printed `76 cases post changed queries; 0 other differences`, `record.py --check` printed `76 fixture files would change`, all of them `druid_query.json`, and `uv run pytest tests/golden tests/druid tests/alerts` gave 76 failed and 210 passed. The 76 failures were exactly the `test_druid_queries` cases of the `--check` list. Ran `record.py <76 cases>`, which wrote 76 files. After: the same pytest run gave 286 passed. `record.py --check` gave `85 cases, 0 fixture files would change`, and so did `tests/golden` under `PYTHONHASHSEED` 0 to 15 (269 passed each). `git diff --stat` shows 76 files, all `druid_query.json`. By sha256, all 85 `expected_response.json`, `druid_response.json`, `request.json` and `case.json` are byte-identical. Independent structural check (not the owner's tool): undo N1 (`selector value null` back to `''`) and N2 (`and(leaf, not(selector dim null))` under a `not`, back to the leaf) on each new fixture. Every fixture then equals the old one, compared modulo the harness's documented and/or operand sort. That makes 93 N1 rewrites in 76 cases (1 to 3 per case): 69 bare has-value tests `not(selector dim null)` and 24 inside the optimiser's merged `not(or[...])`, on StateName 72, MunicipalityName 9, Sex 8 and Age 4 (corrected by data-platform-4 after the qa review; the earlier "Age 5 and Death 1" counted the two N2 guards as N1 rewrites). There are 2 N2 guards, both on `selector` leaves: `filter_not` (Death = 1) and `filter_nested` (Age = 15-49). Neither has an extractionFn, and none sits outside a `not`. `filter_not` also reorders its `or` operands, because the harness sorts operands by compact JSON. After regeneration the drift tool reports a false positive (see the data-platform request).
- 2026-10-05 data-platform-4 merged qa's regeneration (fast-forward to c9f7d8e) and made `check_fixture_drift.py` idempotent over already-guarded N2 leaves; check: `0 cases post changed queries; 0 other differences`, the old-and-new fixture idempotence check fails in 0 of 85, ruff (pyflakes) clean, `uv run pytest tests/golden tests/druid tests/alerts` 286 passed.
- 2026-10-05 core-8a-c (supporting) N3 native LAST_VALUE, 4c1b7fe. Checks:
  - `tests/core/test_last_value_native.py` 11 passed (8 fail without the build hook);
  - `tests/druid/test_last_value_live.py` 20 passed on nojs, sqlnull and druid38 (a tie-dropping mutation fails);
  - native replay of all 90 cases on the three stacks: 0 differences in rows, bodies or errors against `legacy2`;
  - `uv run pytest tests/core tests/druid tests/golden`: 247 passed, 8 skipped (live tests, no ports set), 76 failed. All failures are the pre-existing `test_druid_queries` fixture checks pending the qa regeneration;
  - ruff check and black 22.6 `-S` clean on touched files, and ruff format with quote-style preserved;
  - mypy 1.3.0 clean on `db/druid/aggregations/last_value_aggregation.py` and `db/druid/util.py`.
- 2026-10-05 core-8a-c (supporting) N2 policy check, 6d3a35f: `tests/core/test_policy_exclusion_keeps_nulls.py` 5 passed, all 5 fail with the N2 rewrite removed. N1b is reassigned to the lead (path is outside core). The `''` question is answered from the server side.
- 2026-10-05 core-8a-c merged the WP branch at c9f7d8e (qa's regenerated fixtures) into `mig/WP-8a-druid-js-null-audit-core`; check: `uv run pytest tests/core tests/druid tests/golden tests/alerts` 329 passed, 8 skipped (live LAST_VALUE tests, no ports set), 0 failed. `calc_last_value`'s fixture still matches, because `extension` is the default.
- 2026-10-05 data-platform-4 merged core's N3 (through f1fd768) and declared the qa instance for the 76 regenerated fixtures. Final replays at this head (diff-16 to diff-20): nojs with the default `extension` has 0 result differences; sqlnull and druid38 have 0 with `HARMONY_DRUID_LAST_VALUE=native`, and only `calc_last_value` with `extension`, as expected until WP-8b switches the default. Checks: `uv run pytest tests/golden tests/druid tests/alerts tests/core` 329 passed, 8 skipped (live tests, no ports set); `check_fixture_drift.py` `0 cases post changed queries; 0 other differences`; `task_gate.py` fails only on status and the three pending verdicts. Stopped `wp8a-nojs`, `wp8a-sqlnull` and `wp8a-druid38` and removed their volumes and networks (`wp8a-legacy` earlier); no `wp8a` containers, volumes or networks remain.
- 2026-10-05 data-platform-4 qa review fixes, part 1 (12ed70f and this commit): the S311 and S608 findings are fixed and 6 files formatted with ruff 0.16.10 under integration's config (ruff check and format --check clean on `scripts/druid/null_audit`, `tests/druid` and `db/druid/indexing/common.py`; dataset sha256 unchanged; `tests/druid` 11 passed, 8 skipped; drift check 0/0). The count breakdown is corrected from an independent recount (93 N1 rewrites in 76 cases: StateName 72, MunicipalityName 9, Sex 8, Age 4; 69 bare and 24 merged; N2 guards on Death and Age). Added the `lead` instance and ticked N1b, and routed the `alert.py:198` assert to pipeline. Held until integration is merged: the `druid_javascript_enabled=false` assertion in `tests/druid_setup/test_druid_compose.py` (the file exists only on integration), the MEMORY.md merge conflict, and the replay reruns after core-8a-d.
- 2026-10-05 data-platform-4 security finding (Low): pinned `alpine:3.22.2`, `zookeeper:3.8.4` and `postgres:17.11-bookworm` in `scripts/druid/null_audit/compose.yaml` by the index digests from `docker buildx imagetools inspect` (Postgres equals the existing repo pin). ZooKeeper stays 3.8.4, the version the audit evidence ran on, although integration's `druid_setup` uses 3.8.6; ZooKeeper has no effect on query results. Check: `docker compose ... config --quiet` valid for legacy and druid38 env files; each pinned reference pulls. Renamed the lead instance to `lead-1` for e86d91a.
- 2026-10-05 core-8a-c (supporting) addressed qa's two high core items and security's two low items, on `mig/WP-8a-druid-js-null-audit-core-r2` from the WP head 3f74a71. The `-core` branch name is still checked out in the previous instance's worktree, which this instance cannot detach. Changes:
  - **qa high, DATA-1 (N1c), 1e34633:** `SelectorFilter` and `InFilter` post `''` as `null`. The pushdown and the optimizer hash accept null. See the N1c row and its INV-2 note.
  - **qa high, lint, f679f5b:** the four S101 asserts in `exact_unique_count_aggregation.py` became `TypeError`/`ValueError`, pinned by `tests/core/test_exact_unique_count_merge.py` (4 tests). `db/druid/util.py` and the aggregation module are `ruff format`ted, and the stale "TODO: Javascript filter?" is removed. `data/query/mock/__init__.py` is left untouched so it does not enter the lint set.
  - **security low 1, 5a0ece3:** the native LAST_VALUE posts `accumulatorIdentifier`. It is `__acc` unless the aggregator name, `__time` or the inner field takes it, in which case it gets `_` prefixes (3 new cases in `tests/core/test_last_value_native.py`).
  - **security low 2:** requested from data-platform, because the hook refuses `db/druid/indexing/common.py`. The COUNT_DISTINCT divide-by-zero is recorded as a core follow-up.
  - Checks:
    - `uv run pytest tests/core tests/druid tests/golden tests/alerts`: 345 passed, 8 skipped (live, no ports set);
    - `record.py --check`: 85 cases, 0 fixture files would change;
    - integration's lint rules (ruff 0.16.10, integration's `pyproject.toml`, in a scratch copy) on the 18 core-owned Python files this WP changes: `ruff check` all passed, `ruff format --check` 18 already formatted. The whole-tree E9/F82 pass still flags `util/unix.py` and `scripts/druid/druid_task_memory_stats.py`. Neither file is in this WP's diff, and integration already fixed `util/unix.py`'s import;
    - mypy 1.3.0 `--follow-imports=silent`: clean on the 7 touched modules.

## Evidence

- Unit 3, native epi week:
  - `tests/druid/test_epi_week_native.py`. Six hand-worked dates pin the formula's quirks: week 0 on the ISO year start, week -1 for 1 to 3 January that still sit in the previous ISO year, restart at 0 on 29 to 31 December, week 52. The map is then checked against the Python port on every day from 1900 to 2400, which spans a full 400-year Gregorian cycle.
  - [parity-0.23-legacy.txt](WP-8a-evidence/parity-0.23-legacy.txt) and [parity-0.23-sqlnull.txt](WP-8a-evidence/parity-0.23-sqlnull.txt): `run_audit.py parity --js` groups a one-row-per-day datasource by the JavaScript and the native extraction in the same query. [parity-38-nojs.txt](WP-8a-evidence/parity-38-nojs.txt) and [parity-0.23-nojs.txt](WP-8a-evidence/parity-0.23-nojs.txt): the native extraction on Druid 38 and on 0.23, both with JavaScript disabled.
- Unit 4, null audit: the decision table and diffs above.
- Reproducing the audit:
  - Images: `apache/druid:0.23.0@sha256:ed9719968b4be3a2f1643907a1a5a5814e2ee1215f3604da8b2da2ac05f65912` (compose default) and `apache/druid:38.0.0@sha256:4156a8ca87b855ff6c14f9d95529149b64fe56e25cb394d3043957efae0b9054` (`DRUID_IMAGE`, Java 21.0.10), `postgres:17.11-bookworm`, `zookeeper:3.8.4`.
  - Settings per mode: `scripts/druid/null_audit/modes/*.env`.
  - One compose project per mode: `docker compose --env-file <file with AUDIT_MODE, AUDIT_PORT, AUDIT_DATA, AUDIT_PG_PASSWORD[, DRUID_IMAGE]> -p wp8a-<mode> -f scripts/druid/null_audit/compose.yaml up -d`. When this host's Docker address pools are exhausted, add an override that gives the default network an explicit subnet (`wp8a-legacy` ran on `10.231.8.0/24`).
  - Then `make_dataset.py`, `run_audit.py index [--raw]`, `replay [--candidate]` and `diff`, as in the module docstring.
- Version facts checked against the Druid upgrade notes (fetched 2026-10-04):
  - 32.0.0 removed `useDefaultValueForNull`, `useStrictBooleans=false` and `useThreeValueLogicForNativeFilters=false`; services refuse to start with the legacy values.
  - 38.0.0 removed the ZooKeeper task runner and segment announcement, but ZooKeeper "is still used for Coordinator/Overlord leader election and service (node) announcement and discovery". So 38 still needs ZooKeeper in Compose, which corrects the `harmony-druid` skill's "drop ZooKeeper (38)" for WP-8b.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | changes-requested | 2026-10-05 | 2026-10-05 qa-8a at 3953bee: suites 329 passed under 8 hash seeds; record.py --check 0 changes and drift check 0/0; all 85 expected_response, druid_response, request and case files byte-identical to integration; an independent undo script maps the 76 changed druid_query files back to integration's form (93 N1 rewrites, 2 N2 guards, 0 other); no Druid JavaScript left in eight trees and every druid_setup service renders druid_javascript_enabled=false; every new test file fails on integration code; live replays of 90 cases on one throwaway stack per mode show 0 result differences against a legacy JavaScript-on baseline for legacy, nojs (extension and native), druid38 and sqlnull (native), while integration code on sqlnull shows 64 and on druid38 4 (the check is not vacuous); epi week 0 mismatches over 73414 days plus a direct JavaScript comparison; alert guard keeps 9296 rows in every mode. Fix: (high, blocks) ci/lint_python.sh on the trial merge: S101 asserts in data/alerts/alert.py:198 and db/druid/aggregations/exact_unique_count_aggregation.py (four), S311 make_dataset.py:56, S608 run_audit.py:188, nine files unformatted; merge integration and each owner fixes its files; (high, DATA-1) a saved geo filter can carry '' because data/query/mock/__init__.py:565-568 (run by update_db_datasource.py:135) stores AND(leaf, selector parent '') when the parent is null and the client and server send it back unchanged, so selector StateName '' matches 179 rows on legacy and none under SQL nulls (in [Acre, ''] falls from 4164 to 3985): add a golden case and either build '' as null in SelectorFilter and InFilter or migrate stored dimension_value filters, or record an explicit deferral to WP-8b with a core request; (medium) data/pydruid_query deletion unclaimed, add a lead instance and tick N1b; (low) MEMORY.md trial-merge conflict; (low) no regression test pins druid_javascript_enabled=false (add to tests/druid_setup/test_druid_compose.py and fix its stale comment at :153), drop the TODO at db/druid/util.py:337; (low) WP-8a.md:229 count breakdown wrong (StateName 72, MunicipalityName 9, Sex 8, Age 4 plus two N2 tests). |
| reviewer | pending | |
| security | approved | 2026-10-05 | 2026-10-05 sec-8a at 3953bee: policy parity offline (9 policy shapes over every golden case and the exact COUNT_DISTINCT nested query, 774 runs and 882 filters evaluated under two- and three-valued rules, 0 violations; base code under three-valued rules is stricter on 417 rows, never looser) and live on 0.23 nojs and Druid 38 (five policy shapes incl. an exclusion containing the empty string, groups and counts match a legacy computation, no leaks); JavaScript refused for filters, aggregators, extractions, post-aggregators, ingestion and overlord config; expression injection via field ids refuted (13 ids); harness loopback-only with required random secrets and a pinned extension jar; semgrep 0 over 42 files; ownership clean. Low: harness compose images alpine, zookeeper and postgres pinned by tag only (data-platform); last_value_aggregation.py:64-65,85 the default accumulator name __acc collides with a field id named __acc and drops partial results (core, fix before WP-8b makes native the default); indexing/common.py:31 quote dimension names in the ingest expression (core). WP-8b must carry: Druid authentication and the WP-0b bind-address ruling (druid_setup still publishes every port with postgres:latest and a hard-coded password), JavaScript off in every env file with a permanent test, LAST_VALUE native everywhere with the extension removed, pinned extension downloads and images, a policy probe rerun on 38, and N0 into the WP-8c Parquet schema. Pre-existing for core and QA: exact COUNT_DISTINCT nested query divides by zero when an inner group count is 0. |
