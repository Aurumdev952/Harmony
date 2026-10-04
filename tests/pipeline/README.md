# Pipeline fixture suite (WP-2d)

Proves that harmony_demo's per-row pipeline steps produce the same rows for fixed, small, synthetic inputs:

- `data/pipeline/scripts/process_csv.py`;
- `data/pipeline/self_serve/scripts/process_csv_wrapper.py`, plus the self-serve merge (`MergeDimensionsAndFields` and the lz4 concatenation);
- `data/pipeline/scripts/fill_dimension_data.py`.

The steps run as the Zeus scripts in `pipeline/harmony_demo/process/run/` run them, each in its own subprocess with `ZEN_ENV=harmony_demo`. Every case that completes goes through `fill_dimension_data`, so every case pins Druid rows. This suite is the safety net for WP-8d, the Polars rewrite.

## Run

```bash
tests/pipeline/run.sh                       # all tests, CPython 3.9
tests/pipeline/run.sh -k yellow_fever       # any pytest arguments
PIPELINE_FIXTURE_PYTHON=pypy3.9 tests/pipeline/run.sh   # the interpreter Zeus uses today
CI=1 tests/pipeline/run.sh                  # hypothesis draws the same examples every run
```

You need `uv`, `lz4` and `lz4cat` on `PATH`. If `pigz` is missing, the harness substitutes `gzip`, which gives the same decompressed bytes.

`run.sh` does the following:
- exports `ZEN_ENV=harmony_demo`, whatever the calling shell has;
- keeps hypothesis's cache under `$TMPDIR`;
- installs `requirements.txt`, which pins every direct dependency. `unidecode==1.1.1` matters, because slugified field ids depend on it.

The harness runs each step with `LC_ALL=C.UTF-8` and `TZ=UTC`. The self-serve merge's `sort -u` depends on that locale.

CPython 3.12 and later cannot import `config/` yet, because `ConfigImporter` implements only `find_module`. The suite therefore runs on 3.9, the pipeline image's CPython.

Formatting and lint, as CI runs them today and as WP-2f will:

```bash
uvx --from black==22.6.0 --with click==8.0.4 black --skip-string-normalization -t py39 --check tests/pipeline/*.py
uvx ruff@0.14.0 format --check --line-length 88 --config 'format.quote-style="preserve"' tests/pipeline/*.py
```

## Layout

| Path | Contents |
|---|---|
| `pipeline_cases.py` | Every case: its inputs, then each step's script and arguments |
| `pipeline_fixtures.py` | Runs a case, captures outputs, builds the golden layers |
| `self_serve_merge.sh` | The merge lines of `00_self_serve/10_process`, sourcing the real `util/pipeline/bash/common.sh` |
| `fixtures/` | Synthetic inputs. Names and numbers are invented. The `yellow_fever` codes are public IBGE municipality codes, so the demo join matches |
| `golden/<case>/{contract,canonical,raw}/` | The three golden layers below |
| `test_golden_outputs.py` | Every case against every layer, plus hash-seed and input-format checks |
| `test_properties.py` | Invariants any implementation keeps: ISO dates, the location join, Druid rows, rollup sums |
| `test_pinned_behaviours.py` | Today's quirks that WP-8d keeps or changes on purpose |
| `mutation_check.py` | Applies production mutants to a scratch copy and fails if any survives: `uv run --no-project python tests/pipeline/mutation_check.py` |
| `pipeline_inprocess.py` | In-process access to `_get_date`, `Aggregator`, `BaseRow` and the join, for the two test files above |

A case whose last step is expected to fail pins only its error text (`step<N>.<script>.error.txt`), because partial outputs depend on pipe buffering.

## The three golden layers

**`contract/`** is the INV-2 contract. WP-8d must reproduce it exactly.
- `druid_rollup.jsonl`: what Druid stores after ingest rollup (`db/druid/indexing`). For each (dimensions, `Real_Date`, `source`, `field`) it holds `count`, plus `doubleSum`, `doubleMin` and `doubleMax` of `val`. Collapsed zero rows and nestedJson `data` rows are expanded per field. The sum is `math.fsum`, so row order does not change it.
- `druid_columns.txt`: the Druid column set.
- A case with no Druid rows has empty contract files. A rewrite must also produce none.

**`canonical/`** is today's JSON row layout, with ordering removed:
- `druid_rows.jsonl` and `druid_schema.json`: `val` as int or float, `field` as a string or a list for collapsed zeros, and per-column presence;
- the intermediates: `*.base_rows.jsonl`, `locations*.csv.jsonl`, `fields*.csv.lines.txt`, `metadata_digest_file.csv.jsonl`, `indicators.json`.

A typed Parquet writer cannot reproduce `druid_rows.jsonl` and `druid_schema.json`. WP-8d may change or retire them and the intermediates, recording the change in its WP file.

**`raw/`** is every output file, decompressed, byte for byte: key order, CRLF in `locations.csv` and the digest, shard boundaries, float rendering through `repr`. WP-8d retires the files it no longer writes, recording that in its WP file.

A Parquet-writing reimplementation reads its rows into dicts, calls `contract_rollup` and `contract_columns` from `pipeline_fixtures.py`, and compares against `contract/`.

## Regenerating goldens

```bash
tests/pipeline/run.sh regenerate                  # every case
tests/pipeline/run.sh regenerate CASE [CASE ...]  # some cases
tests/pipeline/run.sh regenerate CASE --print     # show outputs, write nothing
```

Regenerating redefines "unchanged". Every regeneration MUST be recorded in the WP file of the change that needs it, with the cases, the reason, and a summary of the diff (`git diff --stat tests/pipeline/golden`). A reviewer accepts it there (SPEC INV-2). Never regenerate to make a failing test pass without that note, and never hand-edit a golden file.

## What is not covered

- `--policy` is parsed but never read.
- `--output_non_hierarchical` and `--non_hierarchical_mapping_file` do not apply to harmony_demo, which has no non-hierarchical dimensions.
- The fetch steps (curl or `mc` from object storage, `gunzip`, `RemoveBOM`, `gzip`) and `20_sync_digest_files` need the network and object storage. The self-serve case starts from the fetch step's layout: `<source>/config.json` and `<source>/<data>.csv.gz`.

## Behaviour pinned here that a rewrite must decide on deliberately

- Rollup keys use the raw dimension values, before cleaning. `" 210060 "` and `"210060"` become two base rows with identical cleaned dimensions, and Druid's rollup merges them (`demo__yellow_fever_end_to_end`).
- The rollup key joins raw values with `__`. (`Ash__ford`, `Mill`) and (`Ash`, `ford__Mill`) merge into one row, and the second location never reaches `locations.csv` (`test_rollup_keys_collide_when_names_contain_the_key_delimiter`).
- The location join key also joins names with `__`, so the same names collide in `fill_dimension_data` (`test_location_join_keys_collide_when_names_contain_the_key_delimiter`).
- `dateutil` reads `03/04/2020` as 4 March but `15/02/2020` as 15 February (`test_slash_dates_are_month_first_unless_the_first_number_exceeds_twelve`).
- Partial dates take their missing parts from today: `2020` becomes 2020 with today's month and day (`test_partial_dates_take_missing_parts_from_today`). A missing `--date` stamps today's date.
- With `--flatten_string_categories`, a blank value counts as 1 under the bare field id (`process_csv__wide_flatten_string_categories`).
- A `*` disaggregation sums every field of a row into one id (`process_csv__tall_disaggregate`).
- `--tracer_field` is set only on rows that rolled up from two or more input rows.
- `--multi_value_dimensions` reads the column names before `--rename_cols` (`process_csv__wide_multi_value_dimensions`).
- Unmatched rows count in `metadata_digest_file.csv` before the join drops them (`fill_dimension_data__tall_synthetic_join`).
- Without `--shard_size`, every Druid row gets its own shard file (`fill_dimension_data__default_shard_size`).
- `--use_experimental_parser` writes nested `data` rows and leaves the metadata digest empty (`fill_dimension_data__handmade_rows_experimental_parser`). harmony_demo does not use it.

## When WP-8d lands

`pipeline_inprocess.py` imports internals that WP-8d deletes (`_get_date`, `Aggregator`, `BaseRow.to_druid_json_iterator`, `FullRowDimensionDataCollector`). WP-8d rewrites `test_properties.py` and `test_pinned_behaviours.py` against its Polars expressions, keeping each property. The golden cases need only `pipeline_cases.py` pointed at the new entry points, and the contract layer unchanged.
