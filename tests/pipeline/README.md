# Pipeline fixture suite (WP-2d)

Proves that the per-row pipeline steps produce the same rows for fixed small inputs:

- `data/pipeline/scripts/process_csv.py`
- `data/pipeline/self_serve/scripts/process_csv_wrapper.py`
- `data/pipeline/scripts/fill_dimension_data.py`

The steps run as harmony_demo's Zeus scripts run them (`pipeline/harmony_demo/process/run/`), each in its own subprocess with `ZEN_ENV=harmony_demo`. This suite is the safety net for WP-8d, the Polars rewrite.

## Run

```bash
tests/pipeline/run.sh                       # all tests, CPython 3.9
tests/pipeline/run.sh -k yellow_fever       # any pytest arguments
PIPELINE_FIXTURE_PYTHON=pypy3.9 tests/pipeline/run.sh   # the interpreter Zeus uses today
```

You need `uv`, `lz4` and `lz4cat` on `PATH`. If `pigz` is missing, the harness substitutes `gzip`, which gives the same decompressed bytes. Dependencies come from `requirements.txt`, pinned as in `requirements*.txt`. `unidecode==1.1.1` matters, because slugified field ids depend on it.

CPython 3.12 and later cannot import `config/` yet: `ConfigImporter` implements only `find_module`. The suite therefore runs on 3.9, the pipeline image's CPython.

## Layout

| Path | Contents |
|---|---|
| `pipeline_cases.py` | Every case: the inputs, then each step's script and arguments |
| `pipeline_fixtures.py` | Runs a case, captures outputs, canonicalises them |
| `fixtures/` | Synthetic inputs. Names and numbers are invented. The `yellow_fever` codes are public IBGE municipality codes, so the demo join matches |
| `golden/<case>/raw/` | Every output file, decompressed, byte for byte |
| `golden/<case>/canonical/` | The same data, independent of order and container format |
| `test_golden_outputs.py` | Raw and canonical comparison, plus hash-seed and input-format checks |
| `test_properties.py` | Hypothesis properties: date parsing, location join, Druid row writing, rollup |

A case whose last step is expected to fail pins only the error text (`step<N>.<script>.error.txt`), because partial outputs depend on pipe buffering.

## The two golden layers

`raw/` pins today's serialisation exactly: key order, CRLF in `locations.csv` and the digest, shard boundaries, the zero-field collapse, and float rendering through `repr`.

`canonical/` is the contract WP-8d must reproduce:

- `druid_rows.jsonl`: every Druid row, keys sorted, rows sorted. JSON keeps `1` and `1.0` apart, and no number is rounded.
- `druid_schema.json`: the column set, the JSON types per column, and how many rows carry each column. A canonical location without metadata omits its ID and lat/lon columns.
- `druid_rollup.jsonl`: what Druid stores after ingest rollup (`db/druid/indexing`): `count`, `doubleSum`, `doubleMin` and `doubleMax` of `val` per (dimensions, `Real_Date`, `source`, `field`), with collapsed zero rows exploded per field. The sum is `math.fsum`, so row order does not change it.
- `*.base_rows.jsonl`, `locations.csv.jsonl`, `fields.csv.lines.txt`, `metadata_digest_file.csv.jsonl`: the intermediate outputs, sorted.

A reimplementation that writes Parquet should read its rows into dicts and call `canonical_rows`, `canonical_schema` and `canonical_rollup` from `pipeline_fixtures.py`. If WP-8d retires the JSON intermediates, it retires the matching `raw/` files and records that in its WP file.

## Regenerating goldens

```bash
tests/pipeline/run.sh regenerate                  # every case
tests/pipeline/run.sh regenerate CASE [CASE ...]  # some cases
tests/pipeline/run.sh regenerate CASE --print     # show outputs, write nothing
```

Regenerating redefines "unchanged". Every regeneration MUST be recorded in the WP file of the change that needs it, with the cases, the reason, and a summary of the diff (`git diff --stat tests/pipeline/golden`). A reviewer accepts it there (SPEC INV-2). Never regenerate to make a failing test pass without that note, and never hand-edit a golden file.

## Behaviour pinned here that a rewrite must decide on deliberately

- Rollup keys use the raw dimension values, before cleaning. `" 210060 "` and `"210060"` become two base rows with identical cleaned dimensions, and Druid's rollup merges them (`demo__yellow_fever_end_to_end`).
- `dateutil` reads `03/04/2020` as 4 March but `15/02/2020` as 15 February (`test_slash_dates_are_month_first_unless_the_first_number_exceeds_twelve`). A missing `--date` stamps today's date.
- With `--flatten_string_categories`, a blank value counts as 1 under the bare field id (`process_csv__wide_flatten_string_categories`).
- `--tracer_field` is set only on rows that rolled up from two or more input rows.
- `--multi_value_dimensions` reads the column names before `--rename_cols` (`process_csv__wide_multi_value_dimensions`).
- The location join key is the names joined by `__`, so names containing `__` can collide (`test_location_keys_collide_when_names_contain_the_key_delimiter`).
- Unmatched rows count in `metadata_digest_file.csv` before the join drops them (`fill_dimension_data__tall_synthetic_join`).
- Without `--shard_size`, every Druid row gets its own shard file (`fill_dimension_data__default_shard_size`).
- `--use_experimental_parser` writes nested `data` rows and leaves the metadata digest empty (`fill_dimension_data__handmade_rows_experimental_parser`). harmony_demo does not use it.
