---
wp: "2a"
title: "Golden query suite"
status: review
owner_role: "qa"
instances:
  - name: "qa-1"
    files: ["tests/golden/**", "pyproject.toml", "uv.lock", "docs/modernisation/work/WP-2a.md"]
branch: "mig/WP-2a-golden-query-suite"
requirements: [QA-4]
contracts_consumed: [C-3]
contracts_changed: []
security_review: false
---

# WP-2a: Golden query suite

`tests/golden/` judges INV-2. A case POSTs a request through the real `/api2/query` Potion routes on a bare Flask app carrying the `harmony_demo` config, and checks two things:
- the native Druid queries the app posts;
- the body the endpoint returns, given recorded Druid responses.

Only `DruidQueryClient_.run_raw_query`, the HTTP call to the broker, is replaced. No Druid, Postgres or container is needed. Usage, the case format, the normalisation rules and the regeneration policy are in `tests/golden/README.md`.

## Plan

Units, in order. Each line names the change and the check that ends it.

1. **Environment.** Add a minimal root `pyproject.toml` (`requires-python ==3.9.*`, the interpreter in `docker/dev/Dockerfile`) and `uv.lock`. A `golden` dependency group holds the query engine's import closure at the `requirements*.txt` pins, and `dev` holds pytest and freezegun. Check: `uv sync`, and every query, visualization and data quality module imports inside an app context.
2. **Harness, recorder and first case.**
   - `harness.py`: bootstrap; a `DruidQueryClient_` whose broker is a function; the policy identity.
   - `record.py`: regenerates fixtures, with `--check` for a dry run.
   - `synth.py`: a deterministic stand-in broker.
   - `test_golden_queries.py` and one bar graph case.

   Check: the case passes; tampering with `druid_query.json` or `expected_response.json` turns it red.
3. **Case catalogue (75 cases)** and a catalogue test that fails when a POST route, calculation type, filter type or enabled granularity has no case. Check: `uv run pytest tests/golden` is green in under 60 seconds and passes under many `PYTHONHASHSEED` values. `record.py --check` reports no change.
4. **README**: what is pinned, how to run, the case format, normalisation, adding a case, and when regeneration is allowed (only with an INV-2 note in the WP file and reviewer acceptance). Check: the README commands run as written.
5. **Self-verify.** In-memory mutants of the policy filter, query context, date filling, NaN cleaning and metric values turn the suite red. Evidence below.

## Contract changes

None. This WP reads the current query engine and changes no production code.

## Requests

None blocking. Two notes for the lead:
- [ ] infra (WP-2f): this WP adds a minimal root `pyproject.toml` with a `golden` group, `dev` group and `[tool.pytest.ini_options]`. WP-2f should fold it into the `web`/`pipeline`/`dev` groups and keep `uv run pytest tests/golden` working. `psycopg2-binary` is 2.8.6 here, not the 2.8.5 in `requirements.txt`, because 2.8.5 has no CPython 3.9 wheel; only `psycopg2.errorcodes` is imported. `celery` is included only because importing every SQLAlchemy model imports `models.alchemy.schedule`.
- [ ] qa-2 (WP-2c): if WP-2c also adds a root `pyproject.toml`, merge the two by hand. Do not take one side.

## Findings for other roles (pinned by golden cases, not fixed here)

1. **core/backend: a policy filter ANDed with an empty query filter posts an invalid query.**
   - Steps: `uv run pytest tests/golden -k policy_include_all_all_time`, then read `tests/golden/cases/policy_include_all_all_time/druid_query.json`.
   - Request: a non-admin with a state policy, one group with `includeAll` and `includeNull`, and no filter.
   - Expected: a valid Druid filter.
   - Actual: `{"type": "and", "fields": [null, {"type": "in", "dimension": "StateName", "values": ["Acre"]}]}`. The cause is `restrict_query_filter_to_user_permissions` wrapping an `EmptyFilter`, which serialises to `null`. A real broker rejects this.
   - This bears on SEC-4 and WP-0c and 4e. The fix WP updates this case with an INV-2 note.
2. **core: field ids that collide with strict-null count aggregators crash the query.**
   - Example: one field `yellow_fever_cases` (SUM) next to another field with id `yellow_fever_cases__count`.
   - Result: `AssertionError: Attempting to overwrite existing aggregation for key: yellow_fever_cases__count` and HTTP 500.
   - The frontend's generated ids make this unlikely. Not pinned as a case.
3. **data-platform (WP-8a): the JavaScript epi-week extraction is not reachable from harmony_demo.**
   - `epi_week` and `epi_week_of_year` are not enabled there; `/api2/query` answers 404 from the granularity lookup.
   - WP-8a needs a deployment that enables them, or a core-level unit test, to pin that extraction before removing it.
4. **core (WP-1e): `data_quality` never runs outliers** (`query_models.py:266`). `dq_data_quality` pins today's three queries. WP-1e will change it with an INV-2 note.

## Pending regeneration

Not yet executed. Run this only when the lead confirms that WP-0c (branch `mig/WP-0c-pure-mistake-bugs-backend`, test 70ecd0e, fix 64dc60e) is on `mig/integration`. Until then the case keeps characterising today's code, and the suite must keep passing on `mig/integration`.

**INV-2 note for `policy_include_all_all_time`:**
- **Cause.** WP-0c changes `restrict_query_filter_to_user_permissions` to combine filters as `query_filter & policy`. `EmptyFilter.__and__` returns the policy alone, and a None query filter uses the policy itself.
- **Before.** The posted Druid filter is `{"type": "and", "fields": [null, {"type": "in", "dimension": "StateName", "values": ["Acre"]}]}` (Findings, item 1).
- **After.** The posted filter is the policy filter alone, `{"type": "in", "dimension": "StateName", "values": ["Acre"]}`.
- **Why the new output is correct.** A real Druid broker rejected the old request, so no user ever saw a result from it. Nothing a user saw changes. The new query restricts rows exactly as the policy intends.
- **Expected scope.**
  - Only `policy_include_all_all_time/druid_query.json` should change.
  - `druid_response.json` stays byte-identical. The synthetic broker's seed ignores the filter, and the filter rows are the same: the null operand was already ignored when the response was recorded.
  - Therefore `expected_response.json` should stay byte-identical as well.
  - If any other case or file changes, stop and report it. Do not commit it.
- **Commands.**
  1. On a branch containing WP-0c, run `uv run python tests/golden/record.py --check`. It must list only `policy_include_all_all_time/druid_query.json`.
  2. Run `uv run python tests/golden/record.py policy_include_all_all_time`.
  3. Run `uv run pytest tests/golden`.
  4. Update the case description in `case.json` to drop the "a real broker rejects" sentence.
  5. Record the diff here and ask the reviewer to accept it.

## Log

- 2026-10-04 qa-1 unit 1: uv project on CPython 3.9.25; check: `uv sync` OK, all 12 query and data quality modules import in a bare app context (`IMPORT-OK`).
- 2026-10-04 qa-1 unit 2: harness, recorder, synth broker, first case; check: `uv run pytest tests/golden` 3 passed. Tampered `druid_query.json` (`longSum` to `doubleSum`) and `expected_response.json` (375.0 to 375.5) each fail with a diff; restored, 3 passed.
- 2026-10-04 qa-1 unit 3: 75 cases and the catalogue test; check: 226 passed in 1.35 s; 32 `PYTHONHASHSEED` values (0-31) all 226 passed; `record.py --check` under seeds 101, 202 and 303 gives 0 fixture files changed.
- 2026-10-04 qa-1 unit 4: README; check: `record.py --check`, `record.py <case>` and `uv run pytest tests/golden` run as documented; `ruff check` (F, E, W, B, UP, SIM) clean on `tests/golden`.
- 2026-10-04 qa-1 unit 5: mutation evidence below; status review.

## Evidence

**Environment.**
- `uv sync` installs CPython 3.9.25 and the locked set: Flask 1.0.1, Werkzeug 0.16.1, SQLAlchemy 1.3.24, numpy 1.21.0, pandas 1.5.3, pydruid, Flask-Potion and py77 at their git pins, related 0.7.3, freezegun 1.5.5 and pytest 8.4.2.
- The full `requirements*.txt` was not installed: several of its pins, such as psycopg2-binary 2.8.5, do not build on this host. No container was needed.
- `uv pip` is blocked by the modern-python hook, so the environment is the uv project above.

**Suite run.**
```
$ time uv run pytest tests/golden -q -p no:cacheprovider
226 passed, 224 warnings in 1.35s        (2.6 s wall, including uv)
```
- 75 cases × 3 tests (`test_case_is_complete`, `test_druid_queries`, `test_response`), plus `test_catalogue_covers_the_query_surface`.
- The catalogue test checks that cases cover:
  - all 13 POST routes;
  - all 11 calculation types the API accepts (SUM, COUNT, MIN, MAX, AVG, COUNT_DISTINCT, WINDOW, LAST_VALUE, AVERAGE_OVER_TIME, FORMULA, COMPLEX);
  - all 8 filter types;
  - all 9 granularities harmony_demo enables.

**Determinism.**
- `for s in 0..31: PYTHONHASHSEED=$s uv run pytest tests/golden` gave `32 × 226 passed`.
- `PYTHONHASHSEED={101,202,303} uv run python tests/golden/record.py --check` gave `75 cases, 0 fixture files would change`.
- Before having specs were canonicalised, seeds 2, 3 and 5 failed on the order of `havingSpecs` in the sketch-optimisation `having` clause of `dq_data_quality_table` and `dq_field_reporting_stats`. That is how the normalisation list in the README was found.

**Mutation check.** A throwaway pytest plugin patched production code in memory only; no file was edited. Results:

| Mutant | All tests | Query tests only |
|---|---|---|
| policy filter disabled (`restrict_query_filter_to_user_permissions` returns the query unchanged) | 8 failed | 8 failed (every case whose policy adds a filter) |
| `context.timeout` added to every groupBy (what WP-1d will do) | 75 failed | 75 failed, 0 response failures |
| intermediate date filling off | 11 failed | 0 |
| `clean_df_for_json_export` skipped | 38 failed | 0 |
| metrics rounded to 1 decimal after the query | 50 failed | 0 |

**Characterisation on today's code.** The branch changes no production file. `git diff --name-only 488f179..HEAD` lists only:
- `docs/modernisation/work/WP-2a.md`;
- `pyproject.toml` and `uv.lock`;
- `tests/golden/**`.

Every fixture was recorded from, and replays green against, the current code.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | Self-built by qa-1. Needs an independent qa instance or the lead to re-run. |
| reviewer | pending | |
| security | n/a | |
