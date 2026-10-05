# Performance check (PERF-7)

`scripts/perf/` checks that a change does not raise p95 latency on the baseline cases by more than 10% (SPEC PERF-7). Every phase-1 WP (1b to 1g) and every later WP that touches the query path or the bundles runs it and links the result under Evidence.

## What it measures

- **21 query cases.** WP-2a golden request bodies over every `/api2/query/*` endpoint, widened to the synthetic dataset's three years (the raw download, `table_disaggregated`, gets its last month). Each side gets 100 timed requests after 3 warm-up requests, one at a time, with warm caches.
- **3 dashboards.** `perf-mixed-6`, `perf-wide-12` and `perf-heavy-4` (`scripts/perf/dashboards.json`). Each is loaded 30 times in headless Chromium after 2 warm-up loads, and the time to the last rendered tile is recorded.
- **The data.** Druid 0.23 holds `harmony_demo_20261004`: 200,000 yellow-fever cases from `scripts/perf/dataset.py`, seed 20261004, run through the real `process_csv.py` and `fill_dimension_data.py`.

## How the check decides

The host is shared. On 2026-10-05, two runs of one commit differed by up to 287% (`contended-host/`), so absolute numbers cannot be compared from run to run. Instead, the old code (the reference) and your branch (the candidate) run side by side against the same Druid:

- Every round sends the case to both sides, alternating which side goes first.
- Both sides therefore share the host's load.

A case or dashboard fails when either of two ratios is over 1.10 and the lower bound of its paired bootstrap is over 1:

| Ratio | What it catches |
|---|---|
| p95 ratio (candidate p95 / reference p95) | PERF-7 as written. The only check that sees a slowdown confined to the slow tail. |
| paired median ratio (median over rounds of candidate time / reference time in that round) | A slowdown of every request. Shared load cancels within a round, so this sees through noise that hides a 25% slowdown from p95. |

The bounds are one-sided at 5% split across all cases, so an A/A run (both sides the same commit) fails less than one time in twenty.

**Reading the `detects` column.** `detects` is the smallest slowdown of every candidate request that would have failed that case. A pass is only as strong as the largest `detects`, and the run prints that value on its last line.

**Absolute numbers.** p50, p95, bytes, Druid time and host load at start and end are recorded as evidence only.

**Gains show as ratios below 1.** For example, the 1f line-graph target "p50 drops by about a third" reads as a paired median ratio near 0.67 on `line_graph_*`.

## Running it for a WP

All commands run from your worktree. Paired mode needs at least 20 rounds per side. A full run takes about 30 minutes.

1. **Start the stack.** Use the WP-1a stack, or your own copy with the `PERF_*` ports and project set as in the header of `stack.sh`.
   ```bash
   scripts/perf/stack.sh up                      # Druid, web (this checkout) and its data; no re-index if the volumes exist
   scripts/perf/stack.sh ui                      # the production client; rebuilt only when a client input changed
   ```
2. **Start the reference and the run.**
   ```bash
   scripts/perf/stack.sh reference "$(git merge-base HEAD main)"   # the old code, beside yours
   npm ci --ignore-scripts --prefix scripts/perf # Playwright 1.56.1, once
   eval "$(scripts/perf/stack.sh env)"           # the isolation guard refuses eval: export these lines from a script
   uv run --no-project --with requests python scripts/perf/baseline.py --label WP-<id> \
     --dataset "harmony_demo_20261004 (scripts/perf/dataset.py seed 20261004)"
   ```
   The run exits 1 on a regression. It writes `docs/modernisation/perf/paired/<date>-<reference>-vs-<candidate>-WP-<id>.*`. Commit these files, then link the `.md` from your WP file.
3. **Stop the stack.**
   ```bash
   scripts/perf/stack.sh stop                    # keeps volumes; `down` deletes everything
   ```

Use `--case <name>` (repeatable) for a quick look while you work. Only a full run counts as evidence.

## Notes per WP

- **1b (result cache).**
  - Identical requests repeat, so after warm-up the candidate measures the hit path. The phase target, hit-path p50 below 50 ms, is read from the candidate's absolute p50.
  - The miss path is not measured yet. Ask qa for a cache-busting variant before claiming that misses did not slow down.
- **1c (columnar parsing) and 1e (table streaming).**
  - The large cases are `table_disaggregated`, `group_granularity_day`, `map_by_municipality` and `dq_data_quality_table`.
  - The raw download grows superlinearly with its rows. Repro in `probes/` and in the Requests section of `work/WP-1a.md`.
  - Peak memory (1e's `tracemalloc` target) is not recorded yet. Ask qa.
- **1d (timeouts, request-scoped datasource).** No gain is expected. The run must pass.
- **1f (concurrent sub-queries).**
  - The `line_graph_*`, `group_two_totals` and `dq_*` cases run sub-queries.
  - Check `druid_queries` in the absolute tables. It must not change unless the WP explains why.
- **1g (front-end payload).**
  - The client differs from the reference, so `stack.sh reference` builds the reference client too. The build installs about 840 MB of `node_modules` under the scratch directory.
  - Dashboard bytes are in the absolute tables.
  - The "Slow 4G" throttled profile and repeat-visit bytes are not measured yet. Ask qa.
- **Migrations.** Both sides run on the schema left by the candidate's migrations, because web-init runs the candidate's. A reference that cannot run on that schema cannot be paired.
- **Byte counts.** A changed response size is a code change, never noise. The run refuses any case whose size varies between rounds.

## The committed baseline (quiet host only)

`baseline.py --committed` (or `--compare [BASE]`) measures the candidate alone and writes `<date>-<sha>.jsonl` directly under this directory. `--compare` then holds each p95 to 10% above the base. This is phase 1a's original "two consecutive runs agree within 10%" check. It needs a quiet, dedicated host and is open as a human item in `work/WP-1a.md`.

## Files here

| Path | Contents |
|---|---|
| `paired/` | Paired runs: `.reference.jsonl`, `.candidate.jsonl` (`PerfSample` per case), `.rounds.jsonl` (every timed latency, to recompute a verdict), `.meta.json`, `.md` |
| `contended-host/` | The two rejected committed-mode runs that showed the host's noise |
| `probes/` | One-off measurements behind requests to other roles |
