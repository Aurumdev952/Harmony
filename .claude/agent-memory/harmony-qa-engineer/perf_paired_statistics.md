---
name: perf-paired-statistics
description: Why the WP-1a paired PERF-7 check judges two ratios (p95 and per-round median) with a bootstrap bound, and the traps found validating it
metadata:
  type: project
---

The paired PERF-7 gate (`scripts/perf/baseline.py`, lead ruling 2026-10-05) fails a case when either of two ratios is over 1.10 with a paired-bootstrap lower bound over 1 (one-sided 5%, split across cases):
- the p95 ratio;
- the paired median ratio, the median over rounds of candidate/reference in the same round.

**Why:** a bootstrap bound on the p95 ratio alone passed A/A runs but was powerless. On a simulated loaded host it flagged 0 of 24 cases at a true 1.25x slowdown. Independent stalls set p95, and shared load cancels only within a round, so the per-round ratio sees a 1.10x slowdown in every simulated run. The p95 check stays because it alone sees tail-only regressions.

**How to apply:**
- **Reviewing a paired run.** Read `detects`. It is exact, because p95, the median and the seeded bootstrap all scale with the candidate. A pass is only as strong as the largest `detects`.
- **Small samples.** A bootstrap of p95 over fewer than about 20 pairs is anti-conservative: at 4 to 10 pairs, an A/A case fails 2 to 3 times as often as the level says. Paired mode refuses fewer than 20 rounds. A smoke run with 4 dashboard loads "failed" an A/A for exactly this reason.
- **Noise guards.** Before trusting one, push a known regression through it (a power check), not just an A/A run.

See [[perf-stack-real-druid]].
