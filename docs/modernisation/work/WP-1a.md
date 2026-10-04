---
wp: "1a"
title: "Performance baseline"
status: building
owner_role: "qa"
instances:
  - name: "qa-6"
    files: ["scripts/perf/**", "docs/modernisation/perf/**", "docs/modernisation/work/WP-1a.md"]
branch: "mig/WP-1a-perf-baseline"
requirements: [PERF-7]
contracts_consumed: [C-3]
contracts_changed: []
security_review: false
---

# WP-1a: Performance baseline

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Synthetic dataset: `scripts/perf/dataset.py` writes a seeded CSV in the yellow-fever source format (about 200k cases, 2023-01-01 to 2025-12-31, the 579 demo municipalities), and `scripts/perf/stack.sh dataset` runs the real `process_csv.py` and `fill_dimension_data.py` over it with the Zeus arguments. Check: two generations are byte-identical (sha256); step outputs and row counts are recorded.
2. Real Druid: `scripts/perf/stack.sh up|index|down` brings up `druid_setup/single` (Druid 0.23) under a unique project, with no fixed container names, loopback-only ports and scratch shared folders, then runs `run_native_indexing.py` against it. Check: the indexing task succeeds and a native timeseries query over the new datasource returns the generator's total of `yellow_fever_cases`.
3. Web stack on real Druid: the WP-2c contract-stack shape (built web image, Postgres, Redis, Hasura) with `ZEN_OFFLINE` unset, `DRUID_HOST` pointing at the real Druid, and `update_db_datasource.py` run. Check: `/api2/query/bar_graph` returns rows whose total matches the Druid total.
4. `scripts/perf/baseline.py`: fixed cases built from WP-2a golden request bodies (bar, line, table, map, hierarchy, data quality) with the interval widened to the dataset span, replayed with warm-up, writing `PerfSample` JSON lines (p50, p95, bytes, Druid time) and a markdown table under `docs/modernisation/perf/`; `--compare` flags any p95 regression over 10% (PERF-7). Check: unit tests for the statistics and the comparison, and a run against the stack.
5. Dashboard time to last tile: a Playwright script under `scripts/perf/` (the WP-2e harness is not on its branch yet) loading reference dashboards created through the API. Check: a run records time to last tile and bytes per dashboard.
6. Baseline: two consecutive runs agree within 10% (phase-1 verification) and are committed under `docs/modernisation/perf/`. Check: `baseline.py --compare` between the two runs passes.

## Contract changes

None.

## Requests

## Log

- 2026-10-04 qa-6 unit 1: `scripts/perf/dataset.py` (200,000 synthetic cases, seed 20261004, 2023-01-01 to 2025-12-31, 579 demo municipalities); check: CPython 3.9 and 3.13 both write sha256 `fba5ded7a21a9e371343e5a720f4b875406f81b4e35835a00672156f481ed2c9`; `process_csv.py` reads 200,000 rows into 193,959 base rows, `fill_dimension_data.py` writes 387,918 Druid rows (sorted sha256 `4a3d3118…be47`, identical on a second run); field sums 200,000 `yellow_fever_cases` and 1,000,000 `yellow_fever_test_indicator`; ruff check and format clean.
- 2026-10-04 qa-6 unit 2: `scripts/perf/stack.sh dataset|up|index|down` with `scripts/perf/stack/druid.override.yaml` over `druid_setup/single` (Druid 0.23.0, project `harmony-wp1a-perf-druid`, loopback ports 58981/58982/58988, named volumes, `druid` forwarder); check: from nothing, `stack.sh up` took 3 min 43 s, the `index_parallel` task SUCCEEDED, the broker serves `harmony_demo_20261004`, and a native timeseries over it returns `yellow_fever_cases` sum 200000.0 count 193959 and `yellow_fever_test_indicator` sum 1000000.0, the generator's totals; `stack.sh down` leaves no container, volume, network, scratch directory or secrets file; shellcheck and ruff clean. First attempt failed with `NoClassDefFoundError: ...ArrayOfDoublesSketchUnaryPostAggregator` in the peon: `druid_setup`'s extension loader empties the volume on every `up` while JVMs start beside it; the recipe now runs the loader alone first.
- 2026-10-04 qa-6 unit 3: `scripts/perf/stack/web.yaml` (WP-2c stack shape, `ZEN_OFFLINE` unset, `DRUID_HOST=http://druid`, 4 gevent workers) and `init.sh` (migrations, admin, `update_db_datasource.py`); check: login, then `/api2/query/bar_graph` with the golden `bar_graph_sum_by_state_month` body over 2023-01-01..2026-01-01 returns 200, 684 rows (19 states x 36 months) summing to 200000.0, and the broker request log records the query with `query/time`. Migrations import `config/harmony_demo/database.py`, which asks Druid for the newest datasource, so `up` indexes before web-init.

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
