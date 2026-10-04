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

1. Harness: run each step in a subprocess as Zeus does (`ZEN_ENV=harmony_demo`, PYTHONPATH at the repo root, a `pigz` to `gzip` shim when pigz is absent). Capture every output decompressed and canonicalise it. Add `run.sh` and the `regenerate` command. Check: none that runs on its own commit, because no case exists until unit 2 (see Log).
2. Fixtures and goldens for 25 cases. Check: `run.sh` passes, and a tampered golden value fails.
3. Hypothesis properties: date parsing, the location join (oracle), Druid row writing, and process_csv rollup (oracle). Check: 100 examples each.
4. README with the regeneration rule; deslop; ruff. Check: suite on CPython 3.9 and PyPy 3.9.
5. Review round 1 (QA and reviewer changes-requested), as four commits so each golden change can be reviewed alone. Each commit was green when made.
   - 993df54: reformat to black 22.6. Check: 64 passed.
   - 0ebd7dd: harness and the `contract/` / `canonical/` / `raw/` layers, with cases unchanged. Check: 90 passed.
   - b2f50fd: every completing case runs through `fill_dimension_data`; new `--value`, tall `--disaggregate`, `--disaggregate --exclude_zeros` and two-source self-serve cases. Check: 99 passed.
   - 8dfa019: invariants split from pinned quirks, plus the Druid row-count assertion. Check: 103 passed, 1 skipped.
6. README for the three layers, coverage gaps and pinned behaviours (8163f4b). Check: as unit 5.
7. `mutation_check.py`, so reviewers can rerun the mutant evidence (db101ac). Check: exits 0 on a clean export.
8. Review round 2 (reviewer changes-requested). Check: suite green from a clean export on CPython, PyPy, `CI=1` and `ZEN_ENV=et`; formatters and pylint clean; `mutation_check.py` exits 0.
   - e2d2dc4: contract dimensions compared as Druid stores them.
   - ba3d1df: metadata digest pinned in `contract/`.
   - bda45dc: README.

## Contract changes

None.

## Requests

- [ ] infra (WP-2f): put the suite's pinned dependencies into the root `dev` dependency group: `hypothesis==6.91.0`, `contextlib2==21.6.0`, `unidecode==1.1.1`, `python-slugify==8.0.4`, `python-dateutil==2.9.0.post0`, `related==0.7.3`, `attrs==21.4.0`, `six==1.17.0`, `future==0.18.3`, `pytest==8.4.2`, and `pylib` at py77 `70280110ec342a6f6db1c102e96756fcc3c3c01b`. All are listed in `tests/pipeline/requirements.txt`.
  - The root `pyproject.toml` merged from `mig/integration` sets `testpaths = ["tests/golden"]`, so a plain `uv run pytest` does not collect this suite today. Once WP-2f widens `testpaths` to `tests`, it collects `tests/pipeline` and fails at collection unless the root `dev` group has these pins. hypothesis, contextlib2 and unidecode are missing from the `golden` group, and unidecode 1.1.1 is what keeps slugified field ids stable.
  - Today's CI pylint (`integration.yml`, the requirements*.txt venv) reports E0401 `Unable to import 'hypothesis'` for `conftest.py`, `test_properties.py` and `test_pinned_behaviours.py`. With the pins installed, pylint 2.17.4 reports no errors or warnings.
  - Add a CI job that runs `CI=1 tests/pipeline/run.sh` on Python 3.9 with `lz4` installed (`pigz` optional). The lead lands WP-2f first.
- [ ] core: make `config/__init__.py`'s `ConfigImporter` implement `find_spec` / `exec_module`. It implements only `find_module` / `load_module`, which CPython 3.12 removed. On 3.13 the suite fails at import with `ModuleNotFoundError: No module named 'config.datatypes'`. This blocks running `tests/pipeline` on 3.13 (WP-3a), not this WP.
- [ ] pipeline (WP-8d, for information):
  - `contract/` is the INV-2 contract: rollup facts, the column set, and the metadata digest, which is a consumed interface. Dimensions compare as Druid stores them. `canonical/` and `raw/` are layout that WP-8d may change with a recorded note.
  - The README's "Behaviour pinned here" section lists the quirks to keep or change on purpose.
  - `pipeline_inprocess.py` imports internals WP-8d deletes. WP-8d rewrites `test_properties.py` and `test_pinned_behaviours.py`, keeping each property.

## Log

- 2026-10-04 qa-4 unit 0: claimed WP-2d; merged `mig/integration`; branched `mig/WP-2d-pipeline-fixtures`.
- 2026-10-04 qa-4 unit 1: harness, `run.sh`, `regenerate.py` (17890b7). Correction: this commit is not green on its own. `regenerate.py` imports `pipeline_cases`, which arrives in b832f93, so the check could not run at 17890b7. The `run.sh regenerate --print` check first passed at b832f93 and is part of unit 2's evidence.
- 2026-10-04 qa-4 unit 2: 25 fixture cases with raw and canonical goldens (b832f93); check: `tests/pipeline/run.sh` 57 passed. Changing one golden value from `0.30000000000000004` to `0.3` failed the synthetic-join canonical test.
- 2026-10-04 qa-4 unit 3: property tests (c4b20eb); check: 7 passed, 100 examples each, 6 of 106 location tables rejected.
- 2026-10-04 qa-4 unit 4: README, deslop, ruff (62eb926); check: `run.sh` passed 64 on CPython 3.9.25 and 64 on PyPy 3.9.19.
- 2026-10-04 qa-4 unit 5: review round 1, split into 993df54, 0ebd7dd, b2f50fd and 8dfa019 (formerly the single commit 322eb4c; the branch is unpushed, and the rewritten tree equals the old one). Checks: see Plan. Goldens were regenerated deliberately in this unit, with no pipeline code changed, so these are new pins, not changed results.
  - 0ebd7dd (`git diff --stat 993df54 0ebd7dd -- tests/pipeline/golden`): 44 files changed, 88 insertions(+). Six `druid_rollup.jsonl` files moved byte-identical from `canonical/` to `contract/`, plus 38 new contract files. `raw/` and `canonical/` are otherwise unchanged.
  - b2f50fd (`git diff --stat 0ebd7dd b2f50fd -- tests/pipeline/golden`): 189 files changed, 2728 insertions(+), 9 deletions(-).
    - Every completing case gained the join.
    - The wide fixture gained one standalone zero row. The nine existing cases on that fixture each gained one base row, and `process_csv__wide_disaggregate_exclude_zeros` is new: 10 wide cases in all. `process_csv__wide_tab_delimited` uses its own fixture and changed only by gaining the join.
    - `mapped_locations.csv` gained one many-to-one row (`Cedar Point, East`).
    - `demo__self_serve_wrapper` became `demo__self_serve_two_sources`. The 9 deletions are rename-detection artefacts of that move.
  - Whole round (`git diff --stat b8722ff 8dfa019 -- tests/pipeline/golden`): 201 files changed, 2816 insertions(+), 9 deletions(-).
- 2026-10-04 qa-4 unit 6: README (8163f4b); check: as unit 5.
- 2026-10-04 qa-4 unit 7: `tests/pipeline/mutation_check.py` (db101ac); check: exits 0, no mutant survives.
- 2026-10-04 qa-4 merge: `mig/integration` (c6275b1). The `.claude/agent-memory/harmony-qa-engineer/MEMORY.md` add/add conflict is resolved by keeping both sides' lines. `git ls-files .playwright-mcp` is empty. The suite passed after the merge (103 passed, 1 skipped).
- 2026-10-04 qa-4 unit 8: review round 2.
  - e2d2dc4: `contract_rollup` and `contract_columns` compare dimensions as Druid stores them. The new `test_contract_survives_a_typed_table_round_trip` failed for 17 cases against the old functions (with `test_contract_compares_dimensions_as_druid_stores_them`, 18 failed) and passes after. Golden diff (`git diff --stat c6275b1 e2d2dc4 -- tests/pipeline/golden`): 1 file changed, 10 insertions(+), 10 deletions(-). Only `process_csv__wide_multi_value_dimensions/contract/druid_rollup.jsonl` changed: `Sex: []` became absent, and `["X"]`/`["Z"]` became `"X"`/`"Z"`. `canonical/` and `raw/` are unchanged.
  - ba3d1df: `metadata_digest_file.csv.jsonl` joins `contract/`. Golden diff (`git diff --stat e2d2dc4 ba3d1df -- tests/pipeline/golden`): 25 files changed, 76 insertions(+), all added under `contract/`.
  - bda45dc: README.
  - Check: see Evidence.

## Evidence

Every command ran on a clean `git archive` export of bda45dc, outside the repository.

- **Suite:** 28 cases, 130 tests.

  | Mode | Command | Result |
  |---|---|---|
  | CPython 3.9.25 | `tests/pipeline/run.sh -q` | `129 passed, 1 skipped` |
  | CI profile | `CI=1 tests/pipeline/run.sh -q` | `130 passed` (the derandomize check runs only under CI) |
  | PyPy 3.9.19, the interpreter Zeus uses today | `PIPELINE_FIXTURE_PYTHON=pypy3.9 tests/pipeline/run.sh -q` | `129 passed, 1 skipped` |
  | Hostile shell `ZEN_ENV` | `ZEN_ENV=et tests/pipeline/run.sh -q` | `129 passed, 1 skipped` |

- **PyPy parity:** `run.sh regenerate --print` under PyPy and under CPython gave byte-identical output for all 28 cases and 366 output files (`cmp` identical, 4516 lines).
- **Typed-table round trip:** `test_contract_survives_a_typed_table_round_trip` rebuilds each case's Druid rows as a typed columnar writer returns them, then checks that `contract/` is unchanged:
  - every column on every row, missing ones as null;
  - list columns with scalars wrapped;
  - `val` as float;
  - `data` as a struct with null members.

  It passes for all 25 completing cases.
- **Formatting and lint:**
  - `uvx --from black==22.6.0 --with click==8.0.4 black --skip-string-normalization -t py39 --check tests/pipeline/*.py` left 9 files unchanged.
  - `uvx ruff@0.14.0 format --check --line-length 88 --config 'format.quote-style="preserve"' tests/pipeline/*.py` reported 9 files already formatted.
  - pylint 2.17.4 with `.pylintrc`, with the suite's pins installed, reported no errors and no warnings (9.85/10). Without hypothesis it reports only the E0401s listed under Requests.
- **Production mutants:** `uv run --no-project python tests/pipeline/mutation_check.py` applies each mutant alone to a scratch copy of the tree and exits non-zero if any survives. It exited 0, and every mutant fails at least one `contract/` test:

  | Mutant | Failed | Includes |
  |---|---|---|
  | `--value` ignored | 3 | `process_csv__tall_value_column` |
  | Disaggregation keeps zeros under `--exclude_zeros` | 3 | `process_csv__wide_disaggregate_exclude_zeros` |
  | Tall `*` disaggregation ignored | 3 | `process_csv__tall_disaggregate` |
  | Non-zero Druid rows written twice | 70 | `test_druid_rows_carry_every_value_once_and_collapse_zeros_into_one_row` |
  | Rollup key delimiter `__` changed to `\|` | 1 | `test_rollup_keys_collide_when_names_contain_the_key_delimiter` |
  | Rollup max instead of sum | 65 | `test_rollup_sums_each_field_per_dimensions_and_date` |
  | Join metadata not attached | 73 | `test_location_join_returns_canonical_names_and_their_metadata` |

- **Determinism:** `test_outputs_do_not_depend_on_hash_seed` passes with `PYTHONHASHSEED` 1 and 2. Under `CI`, hypothesis is derandomized (`test_ci_draws_the_same_examples_every_run`).
- **Python 3.12+ blocker:** `PIPELINE_FIXTURE_PYTHON=3.13 tests/pipeline/run.sh` fails with `ModuleNotFoundError: No module named 'config.datatypes'`. See Requests.
- **Pipeline surface (`run`):** the suite drives the real command lines of `00_yellow_fever/10_process`, `00_self_serve/10_process` (no sources, and two sources through `MergeDimensionsAndFields` from the real `common.sh`) and `90_shared/10_fill_dimension_data`. The yellow_fever cases use the real `static_data` mapping.
  - Not run: the fetch steps (curl or `mc` from object storage, `gunzip`, `RemoveBOM`) and `20_sync_digest_files`, which need the network and object storage. The self-serve fixtures start from the fetch step's output layout.
  - Not exercised: `--policy` (parsed, never read) and the non-hierarchical flags, which harmony_demo does not use.
- **INV-6:** the fixtures are synthetic. Place names and every value are invented. The yellow_fever fixture uses four public IBGE municipality codes so that the real demo mapping matches.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-05 qa-2d-review at 067ec76: all round-1 findings fixed and reproduced: black and WP-2f ruff clean; three independent mutants and all seven mutation_check.py mutants fail the suite; CI=1 draws identical hypothesis examples twice; PyPy output byte-identical across 28 cases; fixtures synthetic, no volatile data. |
| reviewer | approved | 2026-10-05 rev-2d at b40a444: all four round-2 items closed; the contract holds through a real typed Parquet round trip (25 of 25; the round-trip test fails 18 ways when the normalisation is reverted); digest pinned as an interface; log accurate; split commits each green and the tip identical to 1928f7b. Condition: WP-2f lands first (it carries the pins). |
| security | n/a | |
