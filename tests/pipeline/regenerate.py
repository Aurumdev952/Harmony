"""Rewrite the golden outputs from the current pipeline code.

    tests/pipeline/run.sh regenerate [CASE ...]

Regenerating changes what "unchanged" means. Record the reason and the diff summary in
the WP file of the change that needs it (see README.md).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_cases import CASES  # noqa: E402
from pipeline_fixtures import capture_raw, layers, run_case, write_golden  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases', nargs='*', help='Case names; default is every case.')
    parser.add_argument(
        '--print', action='store_true', help='Print outputs instead of writing goldens.'
    )
    args = parser.parse_args()
    unknown = sorted(set(args.cases) - set(CASES))
    if unknown:
        parser.error(f'unknown cases: {unknown}')
    for name in args.cases or sorted(CASES):
        with tempfile.TemporaryDirectory(prefix=f'wp2d-{name}-') as base:
            case_layers = layers(capture_raw(run_case(CASES[name], Path(base))))
            if args.print:
                for layer, files in case_layers.items():
                    for file_name, data in files.items():
                        print(
                            f'===== {name}/{layer}/{file_name}\n{data.decode()}', end=''
                        )
            else:
                write_golden(name, case_layers)
                counts = ', '.join(
                    f'{len(f)} {layer}' for layer, f in case_layers.items()
                )
                print(f'wrote {name}: {counts}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
