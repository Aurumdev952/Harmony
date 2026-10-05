# Phase 8. Data platform: Druid, pipeline, orchestration

Back to [overview](overview.md). Evidence: [02-architecture-deep-dive.md](02-architecture-deep-dive.md#the-pipeline). Research: [04-technology-research.md](04-technology-research.md#apache-druid).

**Goal.** Make pipeline runs incremental, columnar and observable, and put Druid on a supported release. Use `pstack:show-me-your-work` throughout, and run `pstack:interrogate` before the null-handling and upgrade units ship.

## 8a. Remove Druid JavaScript and audit null handling

- **Changes.**
  - Replace `js_formulas`, week extraction and any JavaScript post-aggregator with native expressions.
  - Set `druid_javascript_enabled=false`.
  - Run the golden suite against a Druid 0.23 instance configured with `druid.generic.useDefaultValueForNull=false`, which is the semantics every current release enforces. List every changed output.
  - For each change, decide whether the new null behaviour is correct, or fix the builder with `COALESCE` or `nvl`.
- **Verification.**
  - The golden suite passes under SQL-compatible nulls.
  - The list of decisions is committed.

## 8b. Upgrade Druid to 37 or 38 on Java 21

- **Changes.**
  - Upgrade in steps through the documented upgrade path, testing each step on the demo deployment.
  - Replace the removed GC flags with `-Xlog:gc*`.
  - ZooKeeper stays (Druid 38 still needs it for leader election and discovery outside Kubernetes; decision 0007), pinned by digest on the internal network.
  - Decision 0007 constraints: basic-security authentication with credentials from secrets, no published ports, JavaScript off with a permanent test, LAST_VALUE native with the extension deleted, extensions and images pinned, the WP-8a policy probe re-run.
  - Update `druid_setup/` single and cluster configs and the extension versions.
  - pydruid stays for building native queries. Transport already went through `harmony.core.druid` in phase 4c.
- **Verification.**
  - Golden suite against a live Druid, and the phase 1 baseline against a live Druid.
  - Ingest the demo dataset and compare row counts and per-field sums with 0.23.

## 8c. Parquet and SQL-based ingestion, month by month

- **Changes.**
  - The index step writes Parquet and submits an MSQ `REPLACE INTO <datasource> OVERWRITE WHERE` for each month whose inputs changed. The input hash per month extends the existing file hash (`run_native_indexing.py:163-176`).
  - The datasource name becomes stable per deployment. The "newest datasource" lookup and `clean_old_datasources.py` are deleted.
  - The datasource version used by the result cache becomes the latest segment version. Replace `sleep 120` with a wait on segment availability.
  - Switch partitioning to range on `field`, then `source`, with `targetRowsPerSegment`.
- **Data structure.** `MonthPartition = {datasource, month, input_hash, segment_version}`, stored in Postgres.
- **Verification.**
  - Change one source file for one month and confirm only that month is reindexed, with the run time recorded.
  - Query results match a full rebuild exactly.

## 8d. Columnar pipeline

- **Changes.**
  - Rewrite `process_csv.py` and `fill_dimension_data.py` as Polars lazy frames that read CSV and Excel, apply the configured cleaners and the location join, roll up, and write Parquet once.
  - Python row hooks still run through `map_elements`, with a warning that names the hook.
  - Delete the lz4 and gzip JSON intermediates and `BaseRow.to_json`.
- **Data structure.** The Parquet schema mirrors the Druid columns: dimensions, `date`, `source`, `field`, `val` and the rollup metrics.
- **Verification.**
  - The pipeline fixture suite from phase 2d produces identical rows.
  - Run on the demo deployment's full input, recording wall time and peak memory against the PyPy run.

## 8e. Dagster in place of cron and Zeus

- **Changes.**
  - Model one asset per source (generate, then process) and one partitioned asset per indexed month. Wrap existing step scripts as ops, unchanged.
  - Retries, failure alerts (email through the existing mailer) and a run-history UI come with Dagster.
  - Delete `prod/cron/pipeline.sh`, the `zeus_*` wrappers, `process_all`'s `|| true` and the Zeus dependency.
  - Move alert evaluation from the pipeline into a Celery beat task that runs after each successful index.
  - Research DHIS2 incremental pulls (`lastUpdated`) for the generate step of DHIS2 sources.
- **Verification.**
  - A failing step marks the run failed and sends an alert.
  - A rerun picks up from the failed asset.
  - The demo deployment runs nightly for a week without anyone intervening.

## 8f. Warehouse decision gate

- **Changes.**
  - Time-boxed to two weeks. Load one real deployment's dataset into a single-node ClickHouse.
  - Port the query builder for bar, line and table visualizations only.
  - Measure p50 and p95 latency on the phase 1 baseline cases, memory, disk, ingest time, and the operator steps needed for install, upgrade and backup.
  - Compare against Druid 37/38 from 8b on the same hardware.
- **Verification.** A written decision with the numbers, reviewed with `pstack:interrogate`. A switch happens only if ClickHouse wins on operator cost without losing on p95 latency. Otherwise the prototype is deleted.
