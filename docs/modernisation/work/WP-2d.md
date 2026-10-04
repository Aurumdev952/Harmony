---
wp: "2d"
title: "Pipeline fixture suite"
status: review
owner_role: "qa"
instances:
  - name: "qa-4"
    files: ["tests/pipeline/**"]
branch: "mig/WP-2d-pipeline-fixtures"
requirements: [QA-4, DATA-4]
contracts_consumed: []
contracts_changed: []
security_review: false
---

# WP-2d: Pipeline fixture suite

`tests/pipeline/` proves that `process_csv.py`, the self-serve `process_csv_wrapper.py` and `fill_dimension_data.py` produce the same rows for fixed, synthetic inputs. It is the safety net for WP-8d (DATA-4). The suite runs under CPython 3.9 and PyPy 3.9 with no services. See `tests/pipeline/README.md`.

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Harness: run each step in a subprocess as Zeus does (`ZEN_ENV=harmony_demo`, PYTHONPATH at the repo root, a `pigz` to `gzip` shim when pigz is absent). Capture every output decompressed. Canonicalise Druid rows into sorted rows, a schema and the Druid rollup facts. Add `run.sh` and the `regenerate` command. Check: `run.sh regenerate --print` runs every case on CPython 3.9.
2. Fixtures and goldens: 25 cases covering:
   - harmony_demo yellow_fever, run end to end against the real static mapping;
   - self-serve, with no sources and through the wrapper;
   - every input format: plain, gzip, lz4, tab-delimited, tall `field,val`, `*field_` wildcard columns;
   - every `process_csv` flag;
   - the `fill_dimension_data` join on synthetic mappings: unmatched, metadata-less and state-level rows, multi-valued dimensions, zero collapse, sharding, the experimental parser, and the abort paths.

   Check: `run.sh` passes; a tampered golden value fails.
3. Hypothesis properties: date parsing, the location join (oracle), Druid row writing (every value carried, zeros collapsed), and process_csv rollup (oracle). Check: 100 examples each, under 6% rejected.
4. README with the regeneration rule; deslop; ruff. Check: `ruff check`, `ruff format --check`, and the full suite on CPython 3.9 and PyPy 3.9.

## Contract changes

None.

## Requests

- [ ] core: make `config/__init__.py`'s `ConfigImporter` implement `find_spec` / `exec_module`. It implements only `find_module` / `load_module`, which CPython 3.12 removed. On 3.13 the suite fails at import with `ModuleNotFoundError: No module named 'config.datatypes'`. This blocks running `tests/pipeline` on 3.13 (WP-3a), not this WP.
- [ ] infra (WP-2f): fold `tests/pipeline/requirements.txt` into the `pipeline` dependency group. Add a CI job that runs `tests/pipeline/run.sh` on Python 3.9 with `lz4` installed (`pigz` optional). qa-2a's root `pyproject.toml` (`requires-python ==3.9.*`) collects `tests/`. This suite keeps its own requirements file so the two branches do not conflict in `pyproject.toml` / `uv.lock`.
- [ ] pipeline (WP-8d, for information): the README's "Behaviour pinned here" section lists current quirks that the Polars rewrite must keep or change on purpose, with a WP note:
  - rollup on raw (uncleaned) dimension values;
  - day/month ambiguity in dateutil parsing;
  - blank cells counting as 1 under `--flatten_string_categories`;
  - `__` join-key collisions;
  - digest counts that include unmatched rows;
  - one shard per row when `--shard_size` is omitted;
  - an empty digest under `--use_experimental_parser`.

## Log

- 2026-10-04 qa-4 unit 0: claimed WP-2d; merged `mig/integration`; branched `mig/WP-2d-pipeline-fixtures`.
- 2026-10-04 qa-4 unit 1: harness, `run.sh`, `regenerate.py` (17890b7); check: `tests/pipeline/run.sh regenerate --print` ran every case, exit 0.
- 2026-10-04 qa-4 unit 2: 25 fixture cases with raw and canonical goldens (b832f93); check: `tests/pipeline/run.sh` 57 passed. Changing one golden value from `0.30000000000000004` to `0.3` failed `test_canonical_outputs_match_golden[fill_dimension_data__tall_synthetic_join]`.
- 2026-10-04 qa-4 unit 3: property tests (c4b20eb); check: 7 passed, 100 examples each, 6 of 106 location tables rejected.
- 2026-10-04 qa-4 unit 4: README, deslop, ruff (62eb926); check: ruff 0.14.0 `check` and `format --check` clean. `run.sh` passed 64 on CPython 3.9.25 (14 s) and 64 on PyPy 3.9.19 (27 s).

## Evidence

All commands run from the worktree root at 62eb926.

- **Suite, CPython:** `tests/pipeline/run.sh -q -W ignore::DeprecationWarning` reported `64 passed in 14.17s`.
- **Suite, PyPy (the interpreter Zeus uses today):** `PIPELINE_FIXTURE_PYTHON=pypy3.9 tests/pipeline/run.sh -q` reported `64 passed in 26.73s`.
- **PyPy parity:** `regenerate.py --print` under PyPy 3.9.19 and under CPython 3.9.25 gave byte-identical output for all 25 cases (1442 lines each, `diff` empty). The CPython goldens are therefore what production writes.
- **Determinism:** `test_outputs_do_not_depend_on_hash_seed` runs the yellow_fever and synthetic-join cases with `PYTHONHASHSEED=1` and `2` and finds identical outputs.
- **Broken code turns the suite red (phase 2 exit check).** Both mutations ran in a scratch copy of the tree, outside the repository:
  - Rollup changed from sum to `max` in `process_csv.py` `_store_values`: 37 failed, 27 passed, including `test_rollup_sums_each_field_per_dimensions_and_date`.
  - Metadata attachment disabled in `FullRowDimensionDataCollector.collect_hierarchical_canonical_dimensions`: 13 failed, 51 passed, including `test_location_join_returns_canonical_names_and_their_metadata`.
- **Python 3.12+ blocker:** `PIPELINE_FIXTURE_PYTHON=3.13 tests/pipeline/run.sh` fails with `ModuleNotFoundError: No module named 'config.datatypes'`. See Requests.
- **Pipeline surface (`run`):** the suite drives the real `pipeline/harmony_demo/process/run/00_yellow_fever/10_process` and `90_shared/10_fill_dimension_data` command lines, with the real `static_data` mapping. The fetch steps (curl to S3, `mc`) were not run, because they need network and object storage.
- **INV-6:** the fixtures are synthetic. Place names (Northvale, Ashford, ...) and every value are invented. The yellow_fever fixture uses four public IBGE municipality codes so that the real demo mapping matches.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | Author is qa-4; an independent qa instance should rerun the evidence. |
| reviewer | pending | |
| security | n/a | |
