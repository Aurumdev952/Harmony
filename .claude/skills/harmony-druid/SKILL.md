---
name: harmony-druid
description: Upgrading Harmony's Apache Druid from 0.23 to 37/38 on Java 21, auditing null handling, removing JavaScript, moving to Parquet with SQL-based (MSQ) REPLACE per month, and partitioning. Use when touching druid_setup, db/druid, ingestion specs, datasource naming, or any query whose results depend on Druid null or empty-string behaviour. No official Druid skill or MCP exists, so this is the reference.
---

# Druid in Harmony

No vendor skill exists. Before relying on any fact below, confirm it against the release notes for the exact target version: https://druid.apache.org/docs/latest/release-info/release-notes and https://druid.apache.org/docs/latest/release-info/upgrade-notes.

## Today

- Druid 38.0.0 on Java 21 after WP-8b (0.23.0 before it), ZooKeeper, Postgres metadata store, local deep storage on NFS.
- `druid_javascript_enabled=false` since WP-8a; permanent tests keep JavaScript out of env files, fixtures and builder sources.
- Native `index_parallel` over sharded gzip JSON (`db/druid/indexing/`) creates a new datasource `<deployment>_<YYYYMMDD…>` on every run. The web app reads the newest one. Two are kept.
- `hashed` partitioning with `numShards: 1` and `segmentGranularity: MONTH` (`db/druid/indexing/common.py:32`).
- The index step waits with a fixed `sleep 120`.

## Version facts that change the plan

- **Java.** 35 and later need Java 17 or 21. 38 drops 17. Target Java 21.
- **JVM flags.** `-XX:+PrintGCTimeStamps` and `-XX:+PrintGCDetails` are gone in modern JVMs. Use `-Xlog:gc*`.
- **ZooKeeper.**
  - ZooKeeper-based segment loading was removed in 30.
  - The ZooKeeper task runner and segment announcement were removed in 38. Use `httpRemote`.
  - ZooKeeper is still required by 38 for leader election and discovery outside Kubernetes; it stays in Compose (decision 0007).
- **Removed ingestion paths.** Hadoop ingestion was deprecated in 32 and removed in 37. Delete `db/druid/indexing/resources/task_templates` (Hadoop) and `tuning_configs/on_prem.json`.
- **Nulls (WP-8a).**
  - SQL-compatible null handling has been the default since 28.
  - `druid.generic.useDefaultValueForNull` and the related legacy flags were removed in 32. Services refuse to start if they are set.
  - `''` is no longer null.
  - Numeric nulls are no longer stored as 0.
  - `x <> 'v'` no longer matches null rows. Add `OR x IS NULL`, or use `IS DISTINCT FROM`.
  - Aggregates over null inputs return null, not 0.
- **MSQ.** MSQ is core from 35 and must not be in `loadList`. Array ingest mode defaults to `array` from 31.
- **Removed settings.** `druid.indexer.runner.type=remote` makes 38 fail to start (`httpRemote` is the default); `druid.serverview.type` must be `http` (38); the `cachingCost` balancer went in 28. 28 and 37 add metadata columns and tables, created automatically while `druid.metadata.storage.connector.createTables` is on.
- **Upgrade path.** No rolling upgrade from before 0.23. A stop-start from 0.23 straight to 38 over the same metadata store and deep storage works: WP-8b served every 0.23 segment on 38 and replayed the golden suite unchanged.

## Druid 38 in druid_setup (WP-8b; decisions 0007 and 0014)

- **Image.** `apache/druid:38.0.0` by digest: Temurin 21.0.10, runs as uid 1000. Every service in `druid_setup` sets a non-root `user`.
- **Authentication.** `druid-basic-security`: chain `["basic"]`, metadata credentials, internal escalator `druid_system`, authorizer `basic`. Every password is an `environment` password provider, never a literal: `druid.sh` echoes every `druid_*` setting into the log. Only the coordinator needs `DRUID_ADMIN_PASSWORD`; every process needs `DRUID_INTERNAL_PASSWORD`. `auth_init` (`druid_setup/auth/provision.sh`) creates and rotates `harmony_query` (web: datasource and STATE read) and `harmony_pipeline` (adds datasource write and EXTERNAL read). `/status/health` is always anonymous; `/status` and `/status/properties` need STATE.
- **Network.** Single mode publishes nothing. Druid, ZooKeeper, Postgres and memcached share an `internal: true` network; the router alone also joins `harmony_druid`, which web, worker and pipeline join, so all of them run on one Docker host (decision 0014). Clients send every request to the router (management proxy on). Cluster mode keeps private-address ports behind authentication, a residual until infra's encrypted overlay (`8b-net`).
- **`druid_host` on an internal network.** The image announces the address of its default route; an `internal: true` network has none, so `druid.host` comes out empty and the router cannot find the coordinator. Set `druid_host` to the service name on every process.
- **Zenysis extensions.** No build newer than 29.0.1 exists. `druid-arbitrary-granularity` 29.0.1 works on 38 and is the only one loaded. `druid-tuple-sketch-expansion` 29.0.1 throws on 38, so the builder keeps theta sketches apart. `druid-aggregatable-first-last` is replaced by the native LAST_VALUE expression aggregator, and nothing reads `nestedJson` any more.
- **Query policies that include `''`.** On 38, `in dim [""]` matches no null row, so such a policy fails closed. Only a JWT `query_needs` claim can produce one; a stored `query_policy` row with `''` grants nothing on either version. `scripts/druid/find_empty_string_policies.py` is the pre-upgrade check (decision 0014).
- **Proof tools.** `scripts/druid/null_audit/run_audit.py` (`--auth-env`; `index`, `replay`, `diff`, `summary`) and `policy_probe.py` replay the golden suite and the policy matrix against a live Druid; `tests/druid_setup/test_druid_auth_live.py` checks authentication from inside the network.

## WP-8a: the null audit, done safely

1. Run the golden suite against Druid 0.23 configured with `druid.generic.useDefaultValueForNull=false`, which gives the same semantics current releases enforce.
2. List every golden case whose output changed in the WP file.
3. For each case, decide whether the new result is correct or a regression. A regression is fixed in the builder (`COALESCE`, `nvl`, explicit `IS NULL` branches). It is never fixed by restoring legacy flags.
4. Replace JavaScript post-aggregators and extraction functions with native expressions. Then set `druid_javascript_enabled=false`.

## WP-8c: Parquet and per-month REPLACE

```sql
REPLACE INTO "<deployment>" OVERWRITE WHERE __time >= TIMESTAMP '2026-09-01' AND __time < TIMESTAMP '2026-10-01'
SELECT TIME_PARSE("date") AS __time, <dimensions>, "source", "field", "val", ...
FROM TABLE(EXTERN(<input source JSON>, '{"type":"parquet"}', <signature>))
WHERE TIME_PARSE("date") >= TIMESTAMP '2026-09-01' AND TIME_PARSE("date") < TIMESTAMP '2026-10-01'
PARTITIONED BY MONTH
CLUSTERED BY "field", "source"
```

- **`OVERWRITE WHERE` accepts only `__time` comparisons.** `PARTITIONED BY` is required. Do not use week granularity.
- **`INSERT`/`REPLACE` map columns by name, not position.** `CLUSTERED BY` implicitly puts `__time` first.
- **Tune `maxNumTasks`** (default 2, minimum 2) and `rowsPerSegment` (default 3,000,000) to the deployment's hardware. Record the chosen values in the WP file.
- **Decide what to reindex from hashes.** A month is reindexed only when its input hash changed. Store hashes in the `MonthPartition` table (SPEC WP-8c data structure).
- **The datasource name is stable per deployment** (contract C-8). The datasource version used by the result cache is the newest segment version. Delete `clean_old_datasources.py` and the "newest datasource" lookup.
- **Wait on segment availability.** Use the SQL `sys.segments` table or the coordinator load-status API. Never use `sleep`.
- **Keep rollup.** The Parquet schema must carry the same columns as today's rollup (`count`, `sum`, `min`, `max` over `val`).

## Querying

- The core builder still emits native JSON through `harmony.core.druid` (pydruid objects for now). New code paths, such as the LLM-facing query API, use Druid SQL over HTTP with parameterised queries. Never interpolate user strings.
- Every query carries `context.timeout` and a `priority`. Dashboard tiles get a higher priority than exports.

## Checks

- Golden suite against a live Druid of the target version.
- Ingest the demo dataset and compare row counts and per-field sums against 0.23.
- Run a single-month change and confirm only that month reindexes. Record the time.
- `docker compose -f druid_setup/single/docker-compose.yml config --quiet` validates (with the five secrets set), and `uv run pytest tests/druid_setup` passes.
- On a live stack: `tests/druid_setup/test_druid_auth_live.py` and `policy_probe.py`.
