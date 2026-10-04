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

## Contract changes

None.

## Requests

- [ ] core: replace J1 with the native extraction (blocks unit 6). In `GranularityExtraction.EXTRACTION_MAP`, set `'epi_week_of_year'` to `CascadeExtraction([TimeFormatExtraction('MM-ww', 'en', 'UTC'), MapLookupExtraction(EPI_WEEK_OF_YEAR_MAP)])`. This needs a small `CascadeExtraction` (`{'type': 'cascade', 'extractionFns': [fn.build() ...]}`), because pydruid has none. The 75-entry map is `tests/druid/epi_week.epi_week_map()`; commit it as a literal next to the extraction. The built dict must equal `epi_week_of_year_extraction()`. Remove the `xfail` marker on `test_builder_emits_the_native_extraction` in the same commit: it is strict, so it fails the day the builder matches. Delete J2 (`db/druid/js_formulas/`) and the J3 branches. Proof that the change is safe: unit 3 evidence. No golden case changes, because harmony_demo does not enable the granularity.
- [x] qa-1a (WP-1a): use of host Druid. Answered by the lead 2026-10-04: WP-1a's `harmony-wp1a-perf-druid` may be used read-only. Not needed. Every WP-8a run uses its own throwaway projects `wp8a-legacy`, `wp8a-sqlnull` and `wp8a-druid38` (ports 58891 to 58893, loopback only, metadata on tmpfs). No WP-8a run touched WP-1a's project.

## Log

- 2026-10-04 data-platform-3 unit 1: inventory above; check: the grep finds nothing outside J1 to J4.
- 2026-10-04 data-platform-3 unit 2: audit harness (`scripts/druid/null_audit/`); check: compose validates per mode, the dataset indexes (9475 input rows, 9459 after rollup), and the legacy replay runs 85 of 85 cases with 0 errors (4 return no rows on purpose: `calc_formula_invalid`, `policy_none`, `policy_source_only`, `policy_jwt_exclude_values`).

- 2026-10-04 data-platform-3 unit 3: native epi week proven; check: `uv run pytest tests/druid` 9 passed, 1 strict xfail (the builder still emits JavaScript, pending the core request); live parity on 0.23 legacy and 0.23 SQL-compatible nulls: 73414 days 1900-01-01..2100-12-31, 0 mismatches between native, JavaScript and the Python port.

## Evidence

- Unit 3, native epi week:
  - `tests/druid/test_epi_week_native.py`. Six hand-worked dates pin the formula's quirks: week 0 on the ISO year start, week -1 for 1 to 3 January that still sit in the previous ISO year, restart at 0 on 29 to 31 December, week 52. The map is then checked against the Python port on every day from 1900 to 2400, which spans a full 400-year Gregorian cycle.
  - [parity-0.23-legacy.txt](WP-8a-evidence/parity-0.23-legacy.txt) and [parity-0.23-sqlnull.txt](WP-8a-evidence/parity-0.23-sqlnull.txt): `run_audit.py parity --js` groups a one-row-per-day datasource by the JavaScript and the native extraction in the same query.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
