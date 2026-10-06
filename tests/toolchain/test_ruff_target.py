"""ruff format emits only syntax the oldest image's interpreter (Python 3.8) parses."""

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Too long for one line, so the formatter has to split the context managers.
CHAINED_WITH = (
    "with open('first_input_file_name.csv') as first_input_file, "
    "open('second_output_file_name.csv', 'w') as second_output_file:\n"
    "    pass\n"
)


def test_format_keeps_chained_with_parseable_by_python_38():
    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'ruff',
            'format',
            '--stdin-filename',
            'web/server/example.py',
            '-',
        ],
        input=CHAINED_WITH,
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
    )
    # Parenthesised context managers are 3.9+ syntax; 3.8 needs the plain form.
    assert 'with (' not in result.stdout, result.stdout
    ast.parse(result.stdout, feature_version=(3, 8))
