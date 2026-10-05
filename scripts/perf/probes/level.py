"""How often does an A/A paired run fail, and what slowdown does it detect?

Simulates whole paired runs (the 21 query cases at 100 rounds and the 3
dashboards at 30, as baseline.py runs them) under three noise models and
judges each case with baseline.paired_result at the production settings
(case_alpha over all cases, 4000 bootstrap resamples; `--split cases`
judges at round 1's level, 5% over the cases only, for comparison):

- `real`: the committed A/A run's own rounds (paired/*-aa.rounds.jsonl), with
  each round's reference and candidate swapped at random. Under A/A the two
  sides of a round are exchangeable, so every swap pattern is another A/A run
  with this host's real noise.
- `stalls-10`, `stalls-25`: a shared load per round (uniform 1 to 3), and per
  request lognormal jitter and an independent stall of 1x to 3x with
  probability 0.10 (jitter 0.15) or 0.25 (jitter 0.30).

A run fails when any case fails. Because both ratios, their bounds and the
seeded bootstrap scale with the candidate, a case fails a uniform slowdown by
k exactly when k > its `detects`, so the same simulated runs also give the
fraction of cases, and of runs, that a uniform slowdown would fail.

    uv run --no-project python scripts/perf/probes/level.py --runs 500 \\
        > docs/modernisation/perf/probes/<date>-level.txt
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import multiprocessing
import random
import sys
from pathlib import Path

PERF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PERF))

import baseline  # noqa: E402

AA_ROUNDS = (
    baseline.RESULTS_DIR / 'paired/2026-10-05-01d5bdf47f-vs-01d5bdf47f-aa.rounds.jsonl'
)
SLOWDOWNS = (1.05, 1.08, 1.10, 1.12, 1.15, 1.20, 1.25)


@functools.lru_cache(maxsize=None)
def committed_rounds() -> dict[str, tuple[list[float], list[float]]]:
    rounds = {}
    for line in AA_ROUNDS.read_text().splitlines():
        record = json.loads(line)
        rounds[record['case_id']] = (record['reference_ms'], record['candidate_ms'])
    return rounds


def swapped(rng: random.Random, reference: list[float], candidate: list[float]):
    pairs = [
        (c, r) if rng.random() < 0.5 else (r, c) for r, c in zip(reference, candidate)
    ]
    return [r for r, _ in pairs], [c for _, c in pairs]


def synthetic(rng: random.Random, n: int, stall_rate: float, jitter: float):
    def latency(load: float) -> float:
        stall = rng.uniform(1, 3) if rng.random() < stall_rate else 1
        return 50 * load * stall * rng.lognormvariate(0, jitter)

    reference, candidate = [], []
    for _ in range(n):
        load = rng.uniform(1, 3)
        reference.append(latency(load))
        candidate.append(latency(load))
    return reference, candidate


MODELS = {
    'real': None,
    'stalls-10': (0.10, 0.15),
    'stalls-25': (0.25, 0.30),
}


# Per-bound level for a run of `cases` cases: the gate's split over both
# bounds of every case, or round 1's split over cases only, for comparison.
SPLITS = {
    'bounds': baseline.case_alpha,
    'cases': lambda cases: baseline.FAMILY_ALPHA / cases,
}


def one_run(job: tuple[str, str, int]) -> list[float]:
    """The `detects` of every case in one simulated A/A run."""
    model, split, run = job
    # Seeded per run so the probe's output is reproducible; not a secret.
    rng = random.Random(f'{model}:{run}')  # noqa: S311
    cases = committed_rounds()
    alpha = SPLITS[split](len(cases))
    detects = []
    for case, (committed_reference, committed_candidate) in cases.items():
        n = len(committed_reference)
        if MODELS[model] is None:
            reference, candidate = swapped(
                rng, committed_reference, committed_candidate
            )
        else:
            reference, candidate = synthetic(rng, n, *MODELS[model])
        # A fresh case id per run, so each run draws its own bootstrap.
        result = baseline.paired_result(f'{case}:{run}', reference, candidate, alpha)
        detects.append(result.detects)
    return detects


def wilson(hits: int, total: int) -> tuple[float, float]:
    """95% Wilson interval of a rate."""
    if total == 0:
        return (0.0, 1.0)
    z = 1.96
    p = hits / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (
        max(0.0, centre - half / (1 + z * z / total)),
        min(1.0, centre + half / (1 + z * z / total)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--runs', type=int, default=500)
    parser.add_argument('--processes', type=int, default=8)
    parser.add_argument('--model', action='append', choices=sorted(MODELS))
    parser.add_argument('--split', choices=sorted(SPLITS), default='bounds')
    args = parser.parse_args()
    shape = {case: len(ref) for case, (ref, _) in committed_rounds().items()}
    print(
        f'cases: {len(shape)} ({sum(n == 100 for n in shape.values())} at 100 rounds, '
        f'{sum(n == 30 for n in shape.values())} at 30)'
    )
    print(
        f'per-bound level ({args.split} split): {SPLITS[args.split](len(shape)):.5f}, '
        f'{baseline.BOOTSTRAP_RESAMPLES} resamples; runs per model: {args.runs}'
    )
    print(f'real-noise source: {AA_ROUNDS.relative_to(baseline.REPO_ROOT)}')
    with multiprocessing.Pool(args.processes) as pool:
        for model in args.model or list(MODELS):
            jobs = [(model, args.split, run) for run in range(args.runs)]
            runs = pool.map(one_run, jobs)
            failed = sum(min(d) < 1 for d in runs)
            low, high = wilson(failed, len(runs))
            print()
            print(f'## {model}')
            print(
                f'A/A runs failed: {failed}/{len(runs)} = {failed / len(runs):.3f} '
                f'(95% CI {low:.3f} to {high:.3f})'
            )
            cases = [d for run in runs for d in run]
            for k in SLOWDOWNS:
                case_rate = sum(d < k for d in cases) / len(cases)
                run_rate = sum(any(d < k for d in run) for run in runs) / len(runs)
                all_rate = sum(all(d < k for d in run) for run in runs) / len(runs)
                print(
                    f'uniform slowdown {k:.2f}: cases failed {case_rate:.3f}, '
                    f'runs with any case failed {run_rate:.3f}, '
                    f'runs with every case failed {all_rate:.3f}'
                )
            print(
                f'median detects {sorted(cases)[len(cases) // 2]:.3f}, '
                f'95th percentile {sorted(cases)[int(len(cases) * 0.95)]:.3f}'
            )


if __name__ == '__main__':
    main()
