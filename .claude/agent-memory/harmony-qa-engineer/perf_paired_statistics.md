---
name: perf-paired-statistics
description: Why the WP-1a paired PERF-7 check judges two ratios (p95 and per-round median) with a bootstrap bound, and the traps found validating it
metadata:
  type: project
---

The paired PERF-7 gate (`scripts/perf/baseline.py`, lead ruling 2026-10-05) fails a case when either of two ratios is over 1.10 with a paired-bootstrap lower bound over 1 (one-sided, 5% split over both bounds of every case, `case_alpha`, since round 2):
- the p95 ratio;
- the paired median ratio, the median over rounds of candidate/reference in the same round.

**Why:** a bootstrap bound on the p95 ratio alone passed A/A runs but was powerless. On a simulated loaded host it flagged 0 of 24 cases at a true 1.25x slowdown. Independent stalls set p95, and shared load cancels only within a round, so the per-round ratio sees a 1.10x slowdown in every simulated run. The p95 check stays because it alone sees tail-only regressions.

**How to apply:**
- **Reviewing a paired run.** Read `detects`. It is exact, because p95, the median and the seeded bootstrap all scale with the candidate. A pass is only as strong as the largest `detects`.
- **Small samples.** A bootstrap of p95 over few pairs is anti-conservative: at 4 to 10 pairs an A/A case fails 2 to 3 times as often as the level says, at 20 about 1.3 times. Paired mode refuses fewer than 30 rounds (decision 0011). A smoke run with 4 dashboard loads "failed" an A/A for exactly this reason.
- **Measure, do not assume, the family rate.** Two bounds per case means the budget splits over 2 x cases. `scripts/perf/probes/level.py` simulates whole runs (real noise by swapping each committed A/A round's sides at random); `rounds.py` gives a bound's level by round count; `sensitivity.py` rejudges a committed run. Under heavy synthetic stalls (25%) the run still fails A/A about 6.6% of the time.
- **Noise guards.** Before trusting one, push a known regression through it (a power check), not just an A/A run.

See [[perf-stack-real-druid]].
