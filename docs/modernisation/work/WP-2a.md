---
wp: "2a"
title: "Golden query suite"
status: ready
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

The production `DruidQueryClient_` runs unchanged. Only the transport is replaced: a `requests` adapter on its pooled session answers each POST from the recording. Three environment patches are listed in the harness docstring and the README:
- an `app.druid_context` stub;
- a frozen clock;
- `is_public_dashboard_user` returning `False`.

No Druid, Postgres or container is needed. Usage, the case format, the normalisation rules and the regeneration policy are in `tests/golden/README.md`.

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
6. **Review round 1** (QA and reviewer changes-requested, 9 findings). Changes:
   - Replace only the transport.
   - Build JWT needs as production does.
   - Add a policy case on every route, and a per-route test that the policy changes the posted queries.
   - Synthesise only real field ids.
   - Set `testpaths` to `tests/golden`.
   - Delete the dead branches.
   - List every case directory.
   - Document every patch.
   - Format with black 22.6 and record the lint commands.

   Check: a clean detached checkout reruns the full evidence, and all mutants turn red, including one unwrapped-client mutant per route.

## Contract changes

None. This WP reads the current query engine and changes no production code.

## Requests

None blocking. Two notes for the lead:
- [ ] infra (WP-2f): this WP adds a minimal root `pyproject.toml` with a `golden` group, `dev` group and `[tool.pytest.ini_options]` (`testpaths = ["tests/golden"]`). WP-2f takes over `pyproject.toml` and `uv.lock`, drops the `golden` group in favour of its `dev` group, and should fold the rest into the `web`/`pipeline`/`dev` groups and keep `uv run pytest tests/golden` working. `psycopg2-binary` is 2.8.6 here, not the 2.8.5 in `requirements.txt`, because 2.8.5 has no CPython 3.9 wheel; only `psycopg2.errorcodes` is imported. `celery` is included only because importing every SQLAlchemy model imports `models.alchemy.schedule`.
- [ ] qa-2 (WP-2c): if WP-2c also adds a root `pyproject.toml`, merge the two by hand. Do not take one side.

## Findings for other roles (pinned by golden cases, not fixed here)

1. **core/backend: a policy filter ANDed with an empty query filter posts an invalid query.**
   - Steps: `uv run pytest tests/golden -k policy_include_all_all_time`, then read `tests/golden/cases/policy_include_all_all_time/druid_query.json`.
   - Request: a non-admin with a state policy, one group with `includeAll` and `includeNull`, and no filter.
   - Expected: a valid Druid filter.
   - Actual: `{"type": "and", "fields": [null, {"type": "in", "dimension": "StateName", "values": ["Acre"]}]}`. The cause is `restrict_query_filter_to_user_permissions` wrapping an `EmptyFilter`, which serialises to `null`. A real broker rejects this.
   - This bears on SEC-4 and WP-0c and 4e. The fix WP updates this case with an INV-2 note.
   - **Resolved by WP-0c** (7584a1a, merged into `mig/integration`). The case was regenerated; see "Regeneration after WP-0c" below.
2. **core: field ids that collide with strict-null count aggregators crash the query.**
   - Example: one field `yellow_fever_cases` (SUM) next to another field with id `yellow_fever_cases__count`.
   - Result: `AssertionError: Attempting to overwrite existing aggregation for key: yellow_fever_cases__count` and HTTP 500.
   - The frontend's generated ids make this unlikely. Not pinned as a case.
3. **data-platform (WP-8a): the JavaScript epi-week extraction is not reachable from harmony_demo.**
   - `epi_week` and `epi_week_of_year` are not enabled there; `/api2/query` answers 404 from the granularity lookup.
   - WP-8a needs a deployment that enables them, or a core-level unit test, to pin that extraction before removing it.
4. **core (WP-1e): `data_quality` never runs outliers** (`query_models.py:266`). `dq_data_quality` pins today's three queries. WP-1e will change it with an INV-2 note.
5. **security (WP-2b): a JWT that only excludes a state gives its holder no data.**
   - Steps: read `tests/golden/cases/policy_jwt_exclude_values/druid_query.json`.
   - Caller: the account may see all states and all sources; the token claim is `query_needs: [{"StateName": {"exclude_values": ["Pará"]}}]`.
   - The intersection in `signal_handlers._compute_token_query_needs` keeps no source need and no Pará exclusion. The posted filter is `source == "__NO_VAL__"`, so the caller gets zero rows.
   - Pinned as today's behaviour.
   - Related, recorded by the reviewer and routed by the lead: `models/python/permissions.py:211-218` (`DimensionFilter.__and__` intersects exclude lists when both sides allow all values).

## Regeneration after WP-0c (executed)

Executed on 2026-10-04 by qa-1, after `git merge mig/integration` brought in WP-0c at 7584a1a. That commit contains 60edb27 and the `and_policy_filter` fix a89c55d.

**Drift check.** Exactly the predicted file changed, and nothing else:

```
$ uv run python tests/golden/record.py --check
would change: policy_include_all_all_time/druid_query.json
85 cases, 1 fixture files would change
```

**Regenerate and verify.**

```
$ uv run python tests/golden/record.py policy_include_all_all_time
written: policy_include_all_all_time/druid_query.json
1 cases, 1 fixture files written
$ uv run pytest tests/golden -q
269 passed
$ uv run python tests/golden/record.py --check
85 cases, 0 fixture files would change
```

**The diff** in `tests/golden/cases/policy_include_all_all_time/druid_query.json`, the only fixture that changed:

```diff
     "filter": {
-      "fields": [
-        null,
-        {
-          "dimension": "StateName",
-          "type": "in",
-          "values": [
-            "Acre"
-          ]
-        }
-      ],
-      "type": "and"
+      "dimension": "StateName",
+      "type": "in",
+      "values": [
+        "Acre"
+      ]
     },
```

- `druid_response.json` and `expected_response.json` are byte-identical, as predicted.
- I removed the "a real broker rejects" sentence from the case description in `case.json`, and the matching known-gap line from the README.
- Reviewer acceptance of this diff is given when PR #5 is merged; the lead recorded that in the PR body.

## Pending regeneration (as planned before WP-0c landed)

Executed as described above. The original instructions follow. Run this only when the lead confirms that WP-0c (branch `mig/WP-0c-pure-mistake-bugs-backend`, test 70ecd0e, fix a89c55d) is on `mig/integration`. Regenerate only against WP-0c at 60edb27 or later. Never regenerate against 64dc60e alone: its pydruid `&` flattened and-shaped request filters in place, which would show up as unrelated golden diffs. Until then the case keeps characterising today's code, and the suite must keep passing on `mig/integration`.

**INV-2 note for `policy_include_all_all_time`:**
- **Cause.** WP-0c changes `restrict_query_filter_to_user_permissions` to combine filters through `and_policy_filter`. A non-empty request filter is posted byte-identically to before. A None or `EmptyFilter` request filter is replaced by the policy filter alone.
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

## INV-2 notes for fixtures re-recorded in review round 1

None of these fixtures has reached `main`. The notes record why recorded outputs changed inside this WP.

1. **`policy_complex_need` and `policy_exclude_values` are replaced by `policy_jwt_complex_need` and `policy_jwt_exclude_values`.**
   - Before: the harness added JWT needs on top of the account's needs, with `all_values` false. That is not how production builds them, so the old cases pinned filters no real user receives.
   - After: the needs are built through `signal_handlers._compute_token_provides`, exactly as `_install_token_needs` does. `all_values` is `not include_values`, and the token needs are intersected with the account's needs.
   - `policy_jwt_complex_need` posts `StateName in [Pará]` and `source in [yellow_fever]`, and returns Pará's row.
   - `policy_jwt_exclude_values` posts `source == "__NO_VAL__"` and returns no rows (Findings, item 5).
   - The case key `query_needs` became `jwt_query_needs`, and the `all_values` key is gone.
2. **`calc_formula`, `calc_formula_invalid`, `calc_formula_with_filter`, `calc_many_fields` and `calc_special_values`: only `druid_response.json` and `expected_response.json` changed.**
   - Cause: the synthetic broker now draws facts only for harmony_demo field ids. Per row, it zeroes an aggregator whose filter no fact passes, and decides emptiness once per distinct aggregator filter. These cases have constituents with different filters, which changes the random draw.
   - Every `druid_query.json` is byte-identical.
   - `calc_formula_invalid` changes from a row with `broken_formula: 262.0` to `"data": []`. A real Druid has no rows for `field == NON_EXISTANT_FIELD`, so the new output is what production returns.
3. **12 new policy cases.** These are 10 per-route policy cases plus the two renamed JWT cases. Every other case's five files are byte-identical to before.

## Log

- 2026-10-04 qa-1 unit 1: uv project on CPython 3.9.25; check: `uv sync` OK, all 12 query and data quality modules import in a bare app context (`IMPORT-OK`).
- 2026-10-04 qa-1 unit 2: harness, recorder, synth broker, first case; check: `uv run pytest tests/golden` 3 passed. Tampered `druid_query.json` (`longSum` to `doubleSum`) and `expected_response.json` (375.0 to 375.5) each fail with a diff; restored, 3 passed.
- 2026-10-04 qa-1 unit 3: 75 cases and the catalogue test; check: 226 passed in 1.35 s; 32 `PYTHONHASHSEED` values (0-31) all 226 passed; `record.py --check` under seeds 101, 202 and 303 gives 0 fixture files changed.
- 2026-10-04 qa-1 unit 4: README; check: `record.py --check`, `record.py <case>` and `uv run pytest tests/golden` run as documented; `ruff check` (F, E, W, B, UP, SIM) clean on `tests/golden`.
- 2026-10-04 qa-1 unit 5: mutation evidence below; status review.
- 2026-10-04 qa-1 unit 6 (review round 1): all 9 findings addressed in ee0e95d. Check, from a clean detached checkout of ee0e95d (`git worktree add --detach /tmp/wp2a-clean ee0e95d`, `uv sync --frozen`):
  - 269 passed;
  - bare `uv run pytest` gives 269 passed;
  - 32 seeds all green;
  - `record.py --check` changes 0 files under 3 seeds;
  - the tamper check turns red;
  - an empty case directory fails `test_case_is_complete`;
  - black and ruff are clean;
  - every mutant turns red (see Evidence).

  The lint claim in unit 4 did not reproduce: it omitted the command and target. It is replaced by the recorded commands below.

## Evidence

**Environment.**
- `uv sync` installs CPython 3.9.25 and the locked set: Flask 1.0.1, Werkzeug 0.16.1, SQLAlchemy 1.3.24, numpy 1.21.0, pandas 1.5.3, pydruid, Flask-Potion and py77 at their git pins, related 0.7.3, freezegun 1.5.5 and pytest 8.4.2.
- The full `requirements*.txt` was not installed: several of its pins, such as psycopg2-binary 2.8.5, do not build on this host. No container was needed.
- `uv pip` is blocked by the modern-python hook, so the environment is the uv project above.

**Re-run after review round 1, from a clean detached checkout of ee0e95d (/tmp/wp2a-clean).**

```
$ git worktree add --detach /tmp/wp2a-clean ee0e95d && cd /tmp/wp2a-clean && uv sync --frozen
$ time uv run pytest tests/golden -q -p no:cacheprovider
269 passed, 307 warnings in 4.64s        (24 s wall, first run including uv's cold start)
$ uv run pytest -q                          # bare run, testpaths = tests/golden
269 passed in 2.24s
$ uv run python tests/golden/record.py --check
85 cases, 0 fixture files would change
$ for s in 0..31: PYTHONHASHSEED=$s uv run pytest tests/golden -q
32 × "269 passed"
$ PYTHONHASHSEED={101,202,303} uv run python tests/golden/record.py --check
85 cases, 0 fixture files would change      (each)
$ uvx --python 3.9 --from black==22.6.0 --with click==8.0.4 black -S -t py39 --check tests/golden
5 files would be left unchanged.
$ uvx ruff@0.14.0 check --target-version py39 --select F,E,W,B,SIM --line-length 88 tests/golden
All checks passed!
```

- **Test count.** 269 = 85 cases × 3 + 13 `test_policy_restricts_every_route` + 1 catalogue test.
- **Tamper check.** `longSum` changed to `doubleSum` in `druid_query.json`, and 375.0 changed to 375.5 in `expected_response.json`, of `bar_graph_sum_by_state_month`. Both fail with a diff; after restoring, 269 passed.
- **Empty case directory.** An empty `cases/zz_incomplete/` fails `test_case_is_complete`, `test_druid_queries` and `test_response`.
- **Mutants** (in-memory pytest plugin, no file edited, run in the clean checkout):

| Mutant | All tests | Query tests only |
|---|---|---|
| policy filter disabled | 31 failed | 18 failed |
| ijson decoding with Decimal (`use_float=False`) | 146 failed | 68 failed |
| `context.timeout` added to every groupBy | 85 failed | 85 failed |
| intermediate date filling off | 11 failed | 0 |
| `clean_df_for_json_export` skipped | 39 failed | 0 |
| metrics rounded to 1 decimal | 55 failed | 0 |
| unwrapped client in `BarGraphVisualization` | 3 failed | 2 failed |
| unwrapped client in `LineGraphVisualization` | 2 failed | 1 failed |
| unwrapped client in `HierarchyVisualization` | 2 failed | 1 failed |
| unwrapped client in `Map` | 2 failed | 1 failed |
| unwrapped client in `TableVisualization` (table and table/disaggregated) | 8 failed | 6 failed |
| unwrapped client in `DataQualityReport` | 2 failed | 1 failed |
| unwrapped client in `DataQualityTable` | 2 failed | 1 failed |
| unwrapped client in `ReportingCompletenessLineGraph` | 2 failed | 1 failed |
| unwrapped client in `OutliersBoxPlot` | 2 failed | 1 failed |
| unwrapped client in `OutliersTable` | 2 failed | 1 failed |
| unwrapped client in `OutliersLineGraph` | 2 failed | 1 failed |
| unwrapped client in `FieldReportingStatsQuery` | 2 failed | 1 failed |

"Unwrapped client" means `QueryBase.__init__` receives the raw `DruidQueryClient_` instead of the `AuthorizedQueryClient` for that one class. In each such row, the failures are that route's policy case and its `test_policy_restricts_every_route`.

**First run, before review (75 cases; superseded by the re-run above).**
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

**Mutation check, first run** (superseded above). A throwaway pytest plugin patched production code in memory only; no file was edited. Results:

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

**Ready (protocol step 8).** After the two optional reviewer nits (e342118) and `git merge mig/integration` (494bc3a):

```
$ uv sync --frozen && uv run pytest tests/golden -q
269 passed in 2.09s
$ uv run python tests/golden/record.py --check
85 cases, 0 fixture files would change
$ uv run --no-project python scripts/agents/task_gate.py WP-2a
WP-2a meets the definition of done gates
```

The first gate run, before the status changed, printed `status is "review", expected ready or done`.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-05 qa-2a-review at ebeeee6: all 9 round-1 findings fixed; 269 pass clean, 3 seeds, integration tip, 0 drift; mutants: policy disabled 31, Decimal decode 146, rounding 55, per-engine bypass 2-8 each (all 12), catalogue. Note: tests/infra needs 3.11+ (WP-2f gives it its own interpreter). |
| reviewer | approved | 2026-10-05 rev-2a re-review at ebeeee6: all eight findings closed; decoder mutant 146 fail; each of 13 routes fails when its policy is dropped; INV-2 notes cover every re-recorded fixture; other cases byte-identical; drift and seeds clean. Optional nits: unused Case.write; string sentinel in run_case. |
| security | n/a | |
