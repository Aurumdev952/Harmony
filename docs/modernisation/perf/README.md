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
- Each side has its own Redis, so neither can answer from bytes the other cached.
- From WP-1b on, both sides run with the result cache off (decision 0011), so a run measures the query path, not cache hits. The one exception is WP-1b's own hit-path check below. Core provides the switch with WP-1b, and qa then sets it in `scripts/perf/stack/web.yaml` for both `web` and `web-reference` (the open request in `work/WP-1a.md`). Until that wiring is committed, `stack.sh` runs the candidate with whatever cache it ships, so no paired run of a branch that contains the result cache is a valid PERF-7 verdict, WP-1b's gate run included.

A case or dashboard fails when either of two ratios is over 1.10 and the lower bound of its paired bootstrap is over 1:

| Ratio | What it catches |
|---|---|
| p95 ratio (candidate p95 / reference p95) | PERF-7 as written. The only check that sees a slowdown confined to the slow tail. |
| paired median ratio (median over rounds of candidate time / reference time in that round) | A slowdown of every request. Shared load cancels within a round, so this sees through noise that hides a 25% slowdown from p95. |

Each bound is one-sided at 5% split over both bounds of every case (Bonferroni: 5% / (2 x 24) per bound), so that an A/A run (both sides the same commit) fails about one time in twenty. Measured by `scripts/perf/probes/level.py` over 500 simulated full runs per noise model (`probes/2026-10-06-level-bounds.txt`):

| Noise | A/A runs that fail (95% interval) | Round 1's split over cases only |
|---|---:|---:|
| This host's real noise (the committed A/A run, each round's sides swapped at random) | 3.0% (1.8 to 4.9) | 4.2% |
| Synthetic: shared load, 10% of requests stall 1x to 3x, jitter 0.15 | 3.6% (2.3 to 5.6) | 6.2% |
| Synthetic, heavy: 25% stall, jitter 0.30 | 6.6% (4.7 to 9.1) | 10.4% |

Under the heaviest synthetic stalls the run still fails more often than 5%: a bootstrap over 30 to 100 rounds is a little optimistic when a quarter of the requests stall. On this host's real noise it holds.

**Reading the `detects` column.** `detects` is the smallest slowdown of every candidate request that would have failed that case. It is exact: both ratios, their bounds and the seeded bootstrap scale with the candidate. A pass is only as strong as the largest `detects`, and the run prints that value on its last line.

**A pass is per case. Read the cases your WP touches.** Each case is judged on its own, so a slowdown confined to one endpoint has to be caught by that endpoint's cases. One case fails a uniform 1.15 slowdown in 14 to 87% of simulated runs, depending on the noise (`probes/2026-10-06-level-bounds.txt`): 86.5% on this host's real noise, 79.3% with 10% stalls, and 14.4% with 25% stalls, where the median `detects` is 1.253. So a localised regression can pass a full run, and on a heavily stalling host it usually will. A WP that changes one endpoint or one visualization reads that endpoint's rows: both ratios and `detects`. If the touched case's `detects` is above 1.10, the run could not have seen a 10% regression there. Add a targeted run of that case with more rounds (`--case <name> --rounds 300 --label WP-<id>-<name>`, which narrows the bound), and file it beside the full run.

**A compliant change can fail.** PERF-7 allows up to 10%, but a case whose `detects` is below 1.10 fails a uniform slowdown of 1.10 or less. Recomputed at the current split, the committed A/A run (`paired/2026-10-05-01d5bdf47f-vs-01d5bdf47f-aa`) fails 1 of 24 cases at a uniform 1.05 slowdown, 3 at 1.08 and 9 at 1.10. In the level simulation on real noise, a uniform 1.05 slowdown fails 4.1% of cases, and 63% of runs fail at least one case. At 1.10, 39% of cases fail and every run fails at least one. The rule is stricter than PERF-7's text by design (decision 0011). The failing-run policy below covers a failure that lands just over the limit.

**When a run fails** (decision 0011, item 4):
- Commit the failing run's files beside the passing ones. Never replace or delete them.
- File a rerun next to the failure with its own label (`--label WP-<id>-rerun1`). Do not rerun until one passes and cite only that pass: the record must show every run. `baseline.py` refuses, before measuring and again before writing, to reuse the name of a run already on disk (same start date, commits and label).
- A failure whose ratio is just above 1.10 goes to the reviewer with the per-case detail: both ratios, both bounds, `detects` and the `.rounds.jsonl`. The reviewer may accept it under PERF-7's text when the case's recorded sensitivity (`detects` below 1.10 in this run or in the A/A run) shows the rule fired on a compliant change. A clear failure (a ratio well above 1.10 with its bound above 1) is a regression to fix.

**Absolute numbers.** p50, p95, bytes, Druid time and host load at start and end are recorded as evidence only.

**Gains show as ratios below 1.** For example, the 1f line-graph target "p50 drops by about a third" reads as a paired median ratio near 0.67 on `line_graph_*`.

## Running it for a WP

All commands run from your worktree. Paired mode needs at least 30 rounds per side (decision 0011): over fewer, the bootstrap of p95 resamples little more than the maximum and an A/A case fails too often. At a 5% level, the p95 bound of an A/A case on real noise exceeds 1 in 14% of cases at 4 rounds, 11% at 10, 6.5% at 20 and 4.1% at 30 (`probes/2026-10-06-rounds.txt`, from `scripts/perf/probes/rounds.py`). A full run takes about 30 minutes.

1. **Start the stack.** Use the WP-1a stack, or your own copy with the `PERF_*` ports and project set as in the header of `stack.sh`.
   ```bash
   scripts/perf/stack.sh up                      # Druid, web (this checkout) and its data; no re-index if the volumes exist
   scripts/perf/stack.sh ui                      # the production client; rebuilt only when a client input changed
   ```
   A web image is built only when its inputs changed, and a failed build stops `stack.sh`. If build containers cannot resolve names (`Temporary failure in name resolution` from pip, or `DNS: transient error` from the extension loader's `apk add`), build on the host's network with `PERF_BUILD_NETWORK=host scripts/perf/stack.sh up` (or `reference`). It covers the web image and Druid's extension loader, the stack's only builds.
2. **Start the reference and the run.** The reference is your WP's base, `git merge-base HEAD mig/integration` (decision 0011), which `stack.sh reference` picks when given no commit. Never use `main`: it is the pre-migration tree, hundreds of commits behind integration, so a run against it would charge your WP with the cost or gain of every WP merged since. The report says when the reference is not that merge base.
   ```bash
   scripts/perf/stack.sh reference               # the old code, beside yours: git merge-base HEAD mig/integration
   npm ci --ignore-scripts --prefix scripts/perf # Playwright 1.56.1, once
   scripts/perf/node_modules/.bin/playwright install chromium   # its browser, once per machine; not in node_modules
   eval "$(scripts/perf/stack.sh env)"           # the isolation guard refuses eval: export these lines from a script
   uv run --no-project --with requests python scripts/perf/baseline.py --label WP-<id> \
     --dataset "harmony_demo_20261004 (scripts/perf/dataset.py seed 20261004)"
   ```
   The run exits 1 on a regression. It writes `docs/modernisation/perf/paired/<date>-<reference>-vs-<candidate>-WP-<id>.*`. Commit these files, then link the `.md` from your WP file.
3. **Stop the stack.**
   ```bash
   scripts/perf/stack.sh stop                    # keeps volumes; `down` deletes everything
   ```
   `stop` lasts only until the Docker daemon restarts. Druid's containers are `restart: always`, so a daemon restart or a reboot starts them again, and they take CPU from everyone else on the host. Run `stop` again afterwards. After a reboot, `up` reruns Druid's extension loader while the JVMs are down, and the loader downloads its jars. If containers cannot reach the internet, `docker start` the stopped Druid containers first: `up` then sees them running and skips the loader. If the stack was last started from a worktree that has since been removed, the `druid` forwarder and the web containers bind-mount files from that worktree and cannot start. Then `docker start` only Druid and its support containers (postgres, zookeeper, memcache, coordinator, broker, historical, middlemanager, router), and run `stack.sh up` from your current worktree, which recreates the forwarder and the web side on your checkout.

## The phase-exit run

When a phase closes (phase 1 after WP-1b to 1g), one more paired run checks the phase as a whole. Each WP's run passes within its own noise, and several small slowdowns can add up. The reference is the integration commit the phase started from, not a merge base (decision 0011, item 2):

```bash
scripts/perf/stack.sh reference <phase start commit on mig/integration>
uv run --no-project --with requests python scripts/perf/baseline.py --label phase-<n>-exit \
  --dataset "harmony_demo_20261004 (scripts/perf/dataset.py seed 20261004)"
```

The report notes that the reference is not the merge base, as it should for this run. The phase's exit evidence links this run, under the same failing-run policy.

Use `--case <name>` (repeatable) for a quick look while you work. Only a full run counts as evidence.

## Notes per WP

- **1b (result cache).**
  - The gate run has the cache off on both sides, like every other WP's run: it shows that the query path did not slow down. It is not valid until qa has wired core's cache switch into `scripts/perf/stack/web.yaml` for `web` and `web-reference`; check that `web.yaml` sets it before running, and ask qa if it does not.
  - The hit-path check is a second run with the cache on for the candidate only. Identical requests repeat, so after warm-up the candidate measures the hit path. The phase target, hit-path p50 below 50 ms, is read from the candidate's absolute p50. That run is evidence for the target, not a PERF-7 verdict.
  - The miss path with the cache on is not measured yet. Ask qa for a cache-busting variant before claiming that misses did not slow down.
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
| `probes/` | One-off measurements behind requests to other roles, and the outputs of `scripts/perf/probes/` (`level.py`: A/A fail rates and power of full runs; `rounds.py`: a bound's level by round count) |
