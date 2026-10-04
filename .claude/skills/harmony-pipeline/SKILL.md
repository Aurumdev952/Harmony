---
name: harmony-pipeline
description: Harmony's pipeline migration, from PyPy per-row scripts run by cron and Zeus to Polars expressions writing Parquet, orchestrated as Dagster OSS assets partitioned by month. Use when touching pipeline/, data/pipeline, util/pipeline, harmony/pipeline, process_csv, fill_dimension_data, location matching or alert evaluation. Layer this on the official polars:polars and dagster:dagster-expert skills.
---

# Harmony pipeline

Load `polars:polars` and `dagster:dagster-expert` first. The Dagster skill says not to answer from memory: run `uv run dg ... --json` and read its references. This skill records Harmony's specifics.

## How it works today

Each deployment has `pipeline/<code>/{generate,process,index,validate}/run/NN_step` executables, run by Zeus (`zeus_<stage>` wrappers) from host cron (`prod/cron/pipeline.sh`).

1. **Process.** `data/pipeline/scripts/process_csv.py` reads CSV with `DictReader`, runs per-row handlers and builds a `BaseRow` per row. It writes LZ4 JSON lines, `locations.csv` and `fields.csv`.
2. **Fill dimensions.** `fill_dimension_data.py` decodes that again, maps raw to canonical locations (exact lookup against `static_data/mapped_locations.csv`), and writes 3M-row gzip JSON shards.
3. **Index.** Druid parses the JSON a third time.
4. **Failure handling.** `process_all:20` swallows failures with `|| true`.

## Rules for the new pipeline

- **Same output, proven first.** The fixture suite from WP-2d (`tests/pipeline/`) must produce identical rows before and after every change.
- **Lazy Polars, one sink.**
  - Use `pl.scan_csv` or `pl.read_excel`, then expressions, then `sink_parquet`.
  - Do not call `.collect()` in the middle of a transform.
  - Do not use `map_elements` except for legacy deployment hooks, which must log `warning: row hook <name> runs per row` (SPEC DATA-4).
- **Parquet schema is contract C-8.** Write types explicitly to match the Druid columns. Keep `''` and null distinct, because Druid 32+ treats them differently (see `harmony-druid`).
- **Location matching is a join.** Join against the mapped-locations table, and report unmatched rows as a Dagster asset check, not as a log line.
- **No PyPy.** It is removed in WP-3b. Do not add PyPy markers or PyPy-specific pins.

## Dagster model (WP-8e)

- Use **Dagster OSS** with a Postgres-backed instance. The vendor skill's MCP is for Dagster+ and does not apply.
- **One asset per source** for each of `generate` and `process`. **One monthly-partitioned asset per deployment** for `index`. A partition maps one-to-one to a Druid `REPLACE ... OVERWRITE WHERE` month window, so re-materialising a partition is idempotent.
- **Wrap existing step scripts as ops first,** unchanged. Rewrite each as Polars when you touch it.
- **Failures stop the run** and send an alert through the existing mailer. Retries are declared per asset. Nothing swallows errors (DATA-5).
- **Alert evaluation** moves to a Celery beat task triggered after a successful index (load `harmony-celery`).
- **Validate definitions** with `uv run dg check defs` and `uv run dg list defs --json` in every unit.

## Deployment configs

`config/<code>/datatypes.py` and `pipeline_sources.py` stay Python. They are read through `harmony.core.deployment` (owned by core). Ask core through the protocol for any change to how they load.

## Checks

```bash
uv run pytest tests/pipeline -q
uv run dg check defs
uv run dg launch --assets '<asset>' --partition 2026-09
```

Also run the full demo pipeline and record wall time and peak memory against the previous run.
