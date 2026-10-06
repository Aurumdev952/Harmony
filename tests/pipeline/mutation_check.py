"""Prove the suite catches broken pipeline code: apply one production mutant at a time
to a scratch copy of the tree and run the suite there. Every mutant must fail.

    uv run --no-project python tests/pipeline/mutation_check.py [MUTANT ...]

The repository itself is never modified.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESS_CSV = 'data/pipeline/scripts/process_csv.py'
NONZERO_ROW = (
    "            yield f'{base_json}, \"field\": \"{key}\", "
    "\"val\": {val}}}{line_ending}'\n"
)

# name: (file, anchor that must occur once, replacement)
MUTANTS = {
    'value_flag_ignored': (
        PROCESS_CSV,
        '    valcol = Flags.ARGS.value\n',
        "    valcol = 'val'\n",
    ),
    'disaggregate_keeps_excluded_zeros': (
        PROCESS_CSV,
        '            if self._should_exclude_value(disagg_val):\n'
        '                continue\n',
        '',
    ),
    'tall_disaggregate_wildcard_ignored': (
        PROCESS_CSV,
        "if field_name != field_id_disagg and field_id_disagg != '*':",
        'if field_name != field_id_disagg:',
    ),
    'druid_nonzero_rows_written_twice': (
        'data/pipeline/datatypes/base_row.py',
        NONZERO_ROW,
        NONZERO_ROW * 2,
    ),
    'rollup_key_delimiter_changed': (
        PROCESS_CSV,
        "dimension_key = '__'.join(",
        "dimension_key = '|'.join(",
    ),
    'rollup_max_instead_of_sum': (
        PROCESS_CSV,
        'baserow_data[key] = value + baserow_data.get(key, 0)',
        'baserow_data[key] = max(value, baserow_data.get(key, 0))',
    ),
    'join_metadata_not_attached': (
        'data/pipeline/datatypes/full_dimension_data_collector.py',
        '        if attach_meta:\n',
        '        if False:\n',
    ),
}


def run_mutant(name: str, scratch: Path) -> list[str]:
    """Return the failing test ids with the mutant applied."""
    relative, anchor, replacement = MUTANTS[name]
    shutil.copytree(
        REPO_ROOT,
        scratch,
        ignore=shutil.ignore_patterns('.git', '.venv', 'node_modules', '__pycache__'),
        symlinks=True,
    )
    target = scratch / relative
    source = target.read_text()
    if source.count(anchor) != 1:
        raise RuntimeError(f'{name}: anchor not found once in {relative}')
    target.write_text(source.replace(anchor, replacement))
    result = subprocess.run(
        [
            str(scratch / 'tests/pipeline/run.sh'),
            '-q',
            '-W',
            'ignore::DeprecationWarning',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    print(f'## {name}: {result.stdout.strip().splitlines()[-1]}')
    return [
        line.split(' ')[1].rsplit('/', 1)[-1]
        for line in result.stdout.splitlines()
        if line.startswith('FAILED')
    ]


def main() -> int:
    names = sys.argv[1:] or list(MUTANTS)
    survivors = []
    for name in names:
        with tempfile.TemporaryDirectory(prefix='wp2d-mutant-') as base:
            failed = run_mutant(name, Path(base) / 'tree')
        for test in failed:
            print(f'   {test}')
        if not failed:
            survivors.append(name)
    if survivors:
        print(f'SURVIVED: {survivors}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
