"""How often does one A/A case's bound exceed 1, by round count?

The reason for baseline.MIN_PAIRED_ROUNDS. A bootstrap of p95 over few pairs
resamples little more than the maximum, so its lower bound is too high and an
A/A case fails more often than the bound's level says. For each round count
and noise model this draws A/A cases (a shared load per round, uniform 1 to
3; per-request lognormal jitter and an independent stall of 1x to 3x) and
judges each with baseline.paired_result at a per-bound level of 5%, so a
calibrated bound exceeds 1 in about 5% of cases. The `real` rows draw from the
committed A/A run instead: n rounds of a random case with at least n rounds,
each round's two sides swapped at random (under A/A they are exchangeable).

    uv run --no-project python scripts/perf/probes/rounds.py \\
        > docs/modernisation/perf/probes/<date>-rounds.txt
"""

from __future__ import annotations

import argparse
import functools
import json
import multiprocessing
import random
import sys
from pathlib import Path

PERF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PERF))

import baseline  # noqa: E402

ROUNDS = (4, 10, 20, 30, 100)
# (stall probability, jitter): no stalls, the WP-1a host's typical noise,
# heavy; None is the committed A/A run's real noise.
MODELS = ((0.0, 0.05), (0.1, 0.15), (0.25, 0.3), None)
LEVEL = 0.05
AA_ROUNDS = (
    baseline.RESULTS_DIR / 'paired/2026-10-05-01d5bdf47f-vs-01d5bdf47f-aa.rounds.jsonl'
)


@functools.lru_cache(maxsize=None)
def committed_cases() -> list[tuple[list[float], list[float]]]:
    lines = AA_ROUNDS.read_text().splitlines()
    return [
        (record['reference_ms'], record['candidate_ms'])
        for record in map(json.loads, lines)
    ]


def one_case(job) -> tuple[bool, bool]:
    n, model, trial, resamples = job
    # Seeded per case so the probe's output is reproducible; not a secret.
    rng = random.Random(f'{n}:{model}:{trial}')  # noqa: S311
    if model is None:
        long_enough = [c for c in committed_cases() if len(c[0]) >= n]
        reference_ms, candidate_ms = rng.choice(long_enough)
        reference, candidate = [], []
        for i in rng.sample(range(len(reference_ms)), n):
            pair = (reference_ms[i], candidate_ms[i])
            if rng.random() < 0.5:
                pair = pair[::-1]
            reference.append(pair[0])
            candidate.append(pair[1])
    else:
        stall_rate, jitter = model

        def latency(load: float) -> float:
            stall = rng.uniform(1, 3) if rng.random() < stall_rate else 1
            return 50 * load * stall * rng.lognormvariate(0, jitter)

        reference, candidate = [], []
        for _ in range(n):
            load = rng.uniform(1, 3)
            reference.append(latency(load))
            candidate.append(latency(load))
    # paired_result refuses short runs; this probe measures why, so it lifts
    # the floor for its own calls.
    baseline.MIN_PAIRED_ROUNDS = 1
    result = baseline.paired_result(
        f't{trial}', reference, candidate, LEVEL, resamples=resamples
    )
    return result.lower > 1, result.shift_lower > 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--trials', type=int, default=1000)
    parser.add_argument('--resamples', type=int, default=1000)
    parser.add_argument('--processes', type=int, default=8)
    args = parser.parse_args()
    print(
        f'per-bound level {LEVEL}, {args.trials} A/A cases per row, '
        f'{args.resamples} bootstrap resamples'
    )
    print('| rounds | noise | p95 bound > 1 | median bound > 1 |')
    print('|---:|---|---:|---:|')
    with multiprocessing.Pool(args.processes) as pool:
        for n in ROUNDS:
            for model in MODELS:
                jobs = [
                    (n, model, trial, args.resamples) for trial in range(args.trials)
                ]
                hits = pool.map(one_case, jobs)
                p95 = sum(h[0] for h in hits) / len(hits)
                median = sum(h[1] for h in hits) / len(hits)
                noise = (
                    'real' if model is None else f'stalls {model[0]}, jitter {model[1]}'
                )
                print(f'| {n} | {noise} | {p95:.3f} | {median:.3f} |', flush=True)


if __name__ == '__main__':
    main()
