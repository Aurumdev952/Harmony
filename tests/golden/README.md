# Golden query suite

This suite judges SPEC invariant INV-2: query results do not change silently. Each case proves two things about the current code:

- A request to `/api2/query/<endpoint>` makes the app post exactly the recorded native Druid queries.
- Given the recorded Druid responses, the endpoint returns exactly the recorded body.

The suite needs no Druid, Postgres or container. It runs in a few seconds:

```bash
uv sync --locked             # once: CPython 3.13 and the locked dependencies
uv run pytest tests/golden
```

## What runs and what is replaced

Each case is POSTed through the real Flask-Potion `QueryResource` routes, on a bare Flask app that carries the `harmony_demo` config (`ZEN_ENV=harmony_demo`). The following all run as in production:

- request validation and conversion (Potion schemas, granularity lookup);
- `QueryRequest` building and the query optimisations;
- the query-policy filter in `AuthorizedQueryClient`, and for JWT callers the token needs from `signal_handlers._compute_token_provides`;
- the production `DruidQueryClient_`:
  - `prepare()` and request serialisation (`requests` with `json=`, which refuses NaN);
  - status handling;
  - gzip and `db/druid/json_stream.py` decoding of streamed responses, or `r.json()` otherwise;
  - response parsing, strict-null handling and subtotal detection;
- the shaping code for each visualization and data quality endpoint, and the response serialisation.

The broker is replaced at the transport. A `requests` adapter, mounted on the client's pooled session for the Druid query URL, receives the serialised POST and answers 200 from `druid_response.json`. Streamed requests get a gzip-encoded body.

Everything else that differs from production is listed here, and `harness.py` patches nothing more:
- `app.druid_context` is a stub with:
  - datasource `harmony_demo_20260101`;
  - data time boundary 2018-01-01 to 2026-01-01;
  - theta sketch sizes.

  The real context reads Postgres and Druid.
- The clock is frozen at 2026-01-15 12:00 (freezegun).
- `web.server.routes.views.query_policy.is_public_dashboard_user` is patched to return `False`. The real function reads the public-access setting from Postgres.
- The Potion authentication decorator is not mounted, and the identity is built from `case.json` rather than loaded from the database.

Route behaviour such as HTTP status, auth and streaming headers belongs to the contract suite (`tests/contract`).

## A case

`cases/<name>/` holds five files:

| File | Content | Written by |
|---|---|---|
| `case.json` | `description`, `endpoint` (the path after `/api2/query/`), `policy`, optional `druid` recording options | hand |
| `request.json` | the POST body, as the frontend serialises it (`serializeForQuery`) | hand |
| `druid_query.json` | every native query posted to Druid, in issue order | `record.py` |
| `druid_response.json` | the raw broker answer to each query | `record.py` |
| `expected_response.json` | the endpoint's response body | `record.py` |

The `policy` field describes the caller:
- `null` is a site administrator, who is never filtered.
- Otherwise it is an object with these keys:
  - `query_policies`: the account's `QueryPolicy` rows as stored, each with `dimension` and `dimension_value` (`null` means all values).
  - `jwt_query_needs` (optional): the `query_needs` claim of a JWT the account signed in with, as a list of `{dimension: {include_values: [...]} | {exclude_values: [...]} | {}}`. When present, the identity's needs are replaced as `signal_handlers._install_token_needs` does: `all_values` is set exactly when `include_values` is empty, and the result is intersected with the account's needs.

The `druid` options are:
- `empty: true`: the broker returns no rows;
- `special_values: true`: post-aggregator values include `NaN`, `Infinity`, `-Infinity` and `null`.

Two tests fail when the catalogue has gaps:
- `test_catalogue_covers_the_query_surface` fails if a POST route, a calculation type, a filter type or a granularity enabled in harmony_demo has no case.
- `test_policy_restricts_every_route[<route>]` fails unless the route has a policy case whose Druid queries differ from the same case replayed as an administrator. So a route that stops applying the query policy turns a golden case red.

## The recorded Druid responses are synthetic

`record.py` answers each query with `synth.synthesize`, a deterministic stand-in for a Druid 0.23 broker. Its answers have:
- array rows for `resultAsArray` groupBy queries, and `{timestamp, result}` objects for timeseries queries;
- `subtotalsSpec` blocks in order, each block sorted by time and then by dimension values, with nulls first;
- rows drawn from a table of facts. The facts cross a sample of the demo locations (states and municipalities with their IDs and coordinates) with sex, age, death, source, and the deployment's real field ids (`config.harmony_demo.indicators.VALID_FIELDS`). The query filter selects facts, so:
  - policies and filters visibly narrow the rows;
  - a field id harmony_demo does not have matches nothing.
- per row, a filtered aggregator that none of the row's facts pass returns zero, with a zero count. Others are empty at random, like a bucket with no reports. Zero counts become nulls through the strict-null fields.
- sparse time buckets, so date filling runs.

Query constructs the cases do not use raise `NotImplementedError` instead of guessing, for example other filter types, period granularities and JavaScript extractions.

Metric values are pseudo-random. The seed is the case name plus the query's structure, so re-recording an unchanged query gives identical bytes. Adding a context key such as a timeout does not change the data.

The responses are not real demo data. They exist to drive the shaping code with Druid-shaped input. Replay never calls `synth.py`. If you change `synth.py`, re-record every case and expect every `druid_response.json` and `expected_response.json` to change. That needs the same INV-2 note as any other regeneration.

## Normalisation

Bodies and queries are compared as canonical JSON: sorted keys, two-space indent, floats in full `repr`, `NaN` and `Infinity` as bare tokens. **Numbers are never rounded or masked.**

The only reordering, in `harness.canonical_query`, is of query parts that the code builds from Python sets. Their order follows `PYTHONHASHSEED`, and Druid treats them as unordered:
- `and`/`or` filter operands and having specs;
- `in` filter values;
- the aggregator list (array result columns are mapped by name).

Dimension order, post-aggregator order and row order are never touched. The suite passes under 32 different `PYTHONHASHSEED` values. Sub-queries are matched by content, so running independent sub-queries concurrently (WP-1f) does not break replay.

## Adding a case

1. Create `cases/<name>/case.json` and `request.json`. Copy a neighbour and keep intervals short: day granularities over two weeks, months over a quarter or a year.
2. Run `uv run python tests/golden/record.py <name>`.
3. Read the three generated files. Check that the query is what you meant, and that the response is not trivially empty unless that is the point.
4. Run `uv run pytest tests/golden` and commit all five files.

## When regenerating an existing case is allowed

A failing golden case means the change altered a Druid query or a result. Do not regenerate to make it pass. Regenerating an existing case is allowed only when all of the following hold:

1. The work package changes the query or the result on purpose.
2. Its WP file has an **INV-2 note**. The note lists:
   - which cases change;
   - the before and after (paste the relevant part of the diff);
   - why the new output is correct;
   - whether only `druid_query.json` changed, or `expected_response.json` too. A query-only change, such as adding `context.timeout` for PERF-2, should leave every `expected_response.json` byte-identical. If a response changes, that is a result change and the note must justify it.
3. The reviewer accepts the note in the WP verdict.

Then regenerate only the named cases:

```bash
uv run python tests/golden/record.py --check          # lists every fixture file that would change
uv run python tests/golden/record.py <case> [<case>...]
```

Commit the regenerated fixtures in the same commit as the code change. That way `git log -p tests/golden/cases` shows every accepted INV-2 difference next to its cause.

## Known gaps and pinned defects

- `epi_week`, `epi_week_of_year` and the fiscal granularities are not enabled in harmony_demo. The granularity lookup returns 404 for them, so the JavaScript epi-week extraction (removed in WP-8a) is not reachable from these cases.
- STOCK and other time-interval indicator calculations, and the `JOIN` request type, do not exist in harmony_demo.
- `GET /api2/query/table?h=` needs a stored query session in Postgres. It is not covered.
- `data_quality` never runs the outlier sub-query, because `query_models.py` computes `include_outliers` as always false (WP-1e). The case pins today's three queries.
- `policy_jwt_exclude_values` pins today's JWT behaviour: a token that only excludes a state leaves no source need after the token-account intersection, so the caller gets `source == __NO_VAL__` and no rows.
- The anonymous public-dashboard branch of `apply_authorization_filters` skips the policy entirely. It is not exercised, because `is_public_dashboard_user` is patched to `False`. The authorisation suite (`tests/authz`) owns that decision.

## Toolchain

The Python files here are formatted and linted with the repo's ruff settings in `pyproject.toml`, as CI checks them:

```bash
uv run --locked ruff format tests/golden
uv run --locked ruff check tests/golden
```
