"""Rejudge a committed paired run at the current rule and show its sensitivity.

For each `.rounds.jsonl` given, recomputes every case with
baseline.paired_result at case_alpha over the run's cases, prints the cases
that regress and, for a set of uniform slowdowns k, how many cases a slowdown
of every candidate request by k would fail (a case fails exactly when
k > its `detects`). This is the per-case detail the failing-run policy in
docs/modernisation/perf/README.md asks for.

    uv run --no-project python scripts/perf/probes/sensitivity.py \\
        docs/modernisation/perf/paired/<run>.rounds.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import baseline  # noqa: E402

SLOWDOWNS = (1.05, 1.08, 1.10, 1.12, 1.15, 1.20)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('rounds', nargs='+', type=Path)
    args = parser.parse_args()
    for path in args.rounds:
        records = [json.loads(line) for line in path.read_text().splitlines() if line]
        alpha = baseline.case_alpha(len(records))
        results = [
            baseline.paired_result(
                r['case_id'], r['reference_ms'], r['candidate_ms'], alpha
            )
            for r in records
        ]
        print(f'{path.name}: {len(results)} cases, per-bound level {alpha:.5f}')
        print(f'  regressed: {[r.case_id for r in results if r.regressed] or "none"}')
        for k in SLOWDOWNS:
            failed = sum(r.detects < k for r in results)
            print(f'  uniform slowdown {k:.2f}: {failed} of {len(results)} cases fail')
        for r in sorted(results, key=lambda r: r.detects):
            print(
                f'  {r.case_id:40} p95 ratio {r.ratio:.3f} (bound {r.lower:.3f})  '
                f'median ratio {r.shift:.3f} (bound {r.shift_lower:.3f})  '
                f'detects {r.detects:.3f}  {baseline.paired_verdict(r)}'
            )


if __name__ == '__main__':
    main()
