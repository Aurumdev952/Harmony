---
wp: "8a"
title: "Remove Druid JavaScript; null-handling audit"
status: building
owner_role: "data-platform"
instances:
  - name: "data-platform-3"
    files: ["druid_setup/**", "scripts/druid/null_audit/**", "tests/druid/**", "docs/modernisation/work/WP-8a.md", "docs/modernisation/work/WP-8a-evidence/**", "docs/modernisation/decisions/*-wp-8a-*.md"]
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

"Builder fixes" are the core requests N1 and N2 below, simulated by `replay --candidate`. The simulation rewrites each posted query at the transport, so it proves the semantics before core lands the code. Core's branch must reproduce the diff-3, diff-6 and diff-7 results with its real builder output.

**Decisions.** Every differing case falls under one of these. None is fixed by restoring legacy flags.

| ID | Change under SQL-compatible nulls | Cases | Decision | Fix |
|---|---|---|---|---|
| N0 | The pipeline's `''` becomes a value of its own, distinct from null, instead of being stored as null. Every "no value" group splits in two (`""` and null), and `''` rows show as `""`. | `dq_data_quality`, `dq_outliers_*`, `group_dimension_include_null`, `table_disaggregated` (raw, both versions) | Regression. Legacy semantics are right for Harmony, where a missing location level means "no value". | Ingest transform `if("<dim>" == '', null, "<dim>")` on every dimension except `field` (`db/druid/indexing/common.py`, this WP). No-op on legacy (diff-8). C-8 (WP-8c) must carry the same rule: Parquet dimensions are null, never `''`. |
| N1 | `selector value ''`, the builder's "has no value" test, matches only `''`, not null. `includeNull: false` groups then keep a null group, and count distinct counts null as a value. | 13 golden cases on sqlnull (the `filter_*`, `group_two_totals`, `hierarchy_*`, `policy_*`, `table_*`, `line_graph_heat_tiles_week` rows in diff-1), 60 once N0 makes the data null; `audit_count_distinct_nullable_dimension` | Regression | Builder emits `selector value null` (core request N1). On 38 three-valued logic happens to hide this, because `not(null = '')` is unknown and the row is dropped. The explicit test is right in both versions. |
| N2 | Three-valued filters (Druid 28+): `NOT dim = v` and `NOT dim IN [...]` drop rows where `dim` is null. Legacy kept them. | `audit_not_selector_query_filter`, `audit_not_selector_calculation_filter`, `audit_not_in_query_filter` on druid38. For example, Acre `yellow_fever_cases` with `NOT Sex = F` falls from 2862.0 to 2656.0. | Regression for INV-2: "everything except females" has always included rows of unknown sex | Builder makes each value comparison under a `not` two-valued: `leaf AND NOT dim IS NULL` (core request N2). No-op on 0.23 (diff-7). |
| N3 | The Zenysis `aggregateLast` extension throws `NullPointerException` (`DelegateCombingColumnValueSelectorFactory.getLong`) under SQL-compatible nulls. It does not exist for 38. | `calc_last_value` | Regression; also blocks WP-8b | Native LAST_VALUE (core request N3, in progress on `mig/WP-8a-druid-js-null-audit-core`) |

Not observed: aggregate-over-null differences, such as a sum over no rows giving null instead of 0. `DruidQueryClient_` already turns zero-count aggregates into null (the strict-null fields), so bodies match.

**For security review.** N2 also rewrites query-policy filters. Today an `exclude_values` policy becomes a `not`. On 38 without N2 it would additionally hide rows whose policy dimension is null. With N2 the policy behaves exactly as today (INV-3). `policy_jwt_exclude_values` is the golden case. It returns no rows in this dataset, so the policy row in the INV-3 suite (`tests/authz`) should confirm.

## Contract changes

None. Note for WP-8c (C-8 owner is this role): the Parquet ingest schema must state that dimension values are null when absent, never `''` (N0).

## Requests

- [ ] core: replace J1 with the native extraction (blocks unit 6). In `GranularityExtraction.EXTRACTION_MAP`, set `'epi_week_of_year'` to `CascadeExtraction([TimeFormatExtraction('MM-ww', 'en', 'UTC'), MapLookupExtraction(EPI_WEEK_OF_YEAR_MAP)])`. This needs a small `CascadeExtraction` (`{'type': 'cascade', 'extractionFns': [fn.build() ...]}`), because pydruid has none. The 75-entry map is `tests/druid/epi_week.epi_week_map()`; commit it as a literal next to the extraction. The built dict must equal `epi_week_of_year_extraction()`. Remove the `xfail` marker on `test_builder_emits_the_native_extraction` in the same commit: it is strict, so it fails the day the builder matches. Delete J2 (`db/druid/js_formulas/`) and the J3 branches. Proof that the change is safe: unit 3 evidence. No golden case changes, because harmony_demo does not enable the granularity.
- [ ] core (N1, blocks unit 5): the "has no value" test becomes `selector value null` instead of `''`. Sites: `data/query/models/dimension.py:45` (`DimensionFilter(...) != ''`), `db/druid/aggregations/exact_unique_count_aggregation.py:70`, `web/server/data/dimension_metadata_util/compute_sketch_sizes.py:130`. Only the posted queries change (`druid_query.json`); every `expected_response.json` stays byte-identical on legacy (diff-7). In progress: core-8a-support on `mig/WP-8a-druid-js-null-audit-core`.
- [ ] pipeline (N1): the same change in `data/alerts/alert.py:96` (`NotFilter(SelectorFilter(..., value=''))`).
- [ ] core (N2, blocks unit 5): inside a negated filter, emit each value comparison (`selector`, `in`, `bound`, `regex`, `search`, `like`) as `and(leaf, not(selector dim null))`. Reference semantics: `scripts/druid/null_audit/run_audit.py` `_two_valued`. Check: the three `audit_not_*` cases match legacy on druid38 (diff-6).
- [ ] core (N3, blocks unit 5 and WP-8b): a native LAST_VALUE that aggregates exactly the rows at the largest timestamp per group, ties included, without the `aggregateLast` extension. Check: `calc_last_value` matches legacy on sqlnull and druid38. In progress: core-8a-support.
- [x] qa-1a (WP-1a): use of host Druid. Answered by the lead 2026-10-04: WP-1a's `harmony-wp1a-perf-druid` may be used read-only. Not needed. Every WP-8a run uses its own throwaway projects `wp8a-legacy`, `wp8a-sqlnull` and `wp8a-druid38` (ports 58891 to 58893, loopback only, metadata on tmpfs). No WP-8a run touched WP-1a's project.

## Log

- 2026-10-04 data-platform-3 unit 1: inventory above; check: the grep finds nothing outside J1 to J4.
- 2026-10-04 data-platform-3 unit 2: audit harness (`scripts/druid/null_audit/`); check: compose validates per mode, the dataset indexes (9475 input rows, 9459 after rollup), and the legacy replay runs 85 of 85 cases with 0 errors (4 return no rows on purpose: `calc_formula_invalid`, `policy_none`, `policy_source_only`, `policy_jwt_exclude_values`).

- 2026-10-04 data-platform-3 unit 3: native epi week proven; check: `uv run pytest tests/druid` 9 passed, 1 strict xfail (the builder still emits JavaScript, pending the core request); live parity on 0.23 legacy and 0.23 SQL-compatible nulls: 73414 days 1900-01-01..2100-12-31, 0 mismatches between native, JavaScript and the Python port.
- 2026-10-04 data-platform-3 unit 4: null audit and the N0 ingest transform; check: decision table above covers every differing case of 9 runs; `uv run pytest tests/druid` 10 passed, 1 strict xfail; native epi week on druid38 with JavaScript off: 0 mismatches.

## Evidence

- Unit 3, native epi week:
  - `tests/druid/test_epi_week_native.py`. Six hand-worked dates pin the formula's quirks: week 0 on the ISO year start, week -1 for 1 to 3 January that still sit in the previous ISO year, restart at 0 on 29 to 31 December, week 52. The map is then checked against the Python port on every day from 1900 to 2400, which spans a full 400-year Gregorian cycle.
  - [parity-0.23-legacy.txt](WP-8a-evidence/parity-0.23-legacy.txt) and [parity-0.23-sqlnull.txt](WP-8a-evidence/parity-0.23-sqlnull.txt): `run_audit.py parity --js` groups a one-row-per-day datasource by the JavaScript and the native extraction in the same query. [parity-38-nojs.txt](WP-8a-evidence/parity-38-nojs.txt): the native extraction on Druid 38 with JavaScript disabled.
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
| qa | pending | |
| reviewer | pending | |
| security | pending | |
