# 0011. PERF-7 is judged by a paired A/B run with a median-of-ratios rule

Status: applied by the lead on 2026-10-05, pending human ratification (SPEC section 10).

## Context

PERF-7 says no phase may raise p95 latency on the baseline cases by more than 10%, and the phase-1 text for 1a asked for a committed baseline where "two consecutive runs agree within 10%". On the shared, loaded development host (load average 8 to 60) absolute p95 numbers do not reproduce: the WP-1a builder's first design could not pass its own A/A run, and the lead ruled option 3, a paired comparison. The WP-1a reviewer and QA then measured the paired design on the committed A/A rounds:

- a bare p95 ratio (new p95 over old p95 per case) fails an A/A run on this host (`perf-wide-12` came in at 1.19) and, alone, passes a uniform 25% slowdown on 10 of 24 cases;
- the per-round median of new-over-old ratios, with a seeded whole-round bootstrap lower bound, passes every A/A run and fails every uniform slowdown of 1.21 or more in every case, 1.12 in 18 of 24;
- at a 1.05 uniform slowdown one case still fails and at 1.10 twelve do, so the rule can fail a change PERF-7's text allows.

That makes the rule stricter than the text, which is why it needs a decision rather than a builder's choice.

## Decision

1. **Gate for WP-1b to 1g and for every phase exit.** A case fails when either (a) its p95 ratio exceeds 1.10 with the bootstrap lower bound above 1, or (b) the median over rounds of new-over-old latency in the same round exceeds 1.10 with its lower bound above 1. Both run against the same Druid with interleaved requests, old and new alternating first within each round, at least 30 rounds per case, a fresh browser context per dashboard load, the bootstrap seeded from the case id and round count.
2. **Reference.** The reference is the WP's base, `git merge-base HEAD mig/integration`, never `main`; a phase-exit run uses the phase's start commit on integration as the reference.
3. **Caches.** From WP-1b on, both sides run with the result cache off, except WP-1b's own hit-path check; the reference web gets its own Redis. Core provides the switch with WP-1b.
4. **Failing runs.** A failing run is committed beside the passing ones, never replaced; a rerun is filed next to the failure; a failure with a ratio just above 1.10 goes to the reviewer with the per-case detail, who may accept it under PERF-7's text when the case's recorded sensitivity shows the rule fired on a compliant change.
5. **Absolute baseline.** The committed-baseline mode stays behind a flag for a quiet window or a dedicated machine (human item); the phase-1 1a verification text now reads "an A/A paired run passes on the development host; the absolute baseline is recorded when a quiet window exists".

## Consequences

- WP-1a's reviewer finding on the reference and the shared Redis become requirements of that WP; the median rule is no longer an open decision.
- `docs/modernisation/perf/README.md` states the rule, its measured fail rates and the failing-run policy.
- The human may overturn this by accepting absolute runs only; then phase 1 waits for the quiet window.
