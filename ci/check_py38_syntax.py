"""Fail on Python 3.9+ syntax in code the Python 3.8 web image runs.

Run it with a real CPython 3.8 (CI: `uv run --no-project -p cpython-3.8.20`), whose
parser rejects 3.9+ syntax such as `with (open(a) as x, open(b) as y):`. The one
3.9+ form that 3.8 still parses, `with (a, b):`, is a tuple there and fails only
when it runs, so a with-item whose context is a bare tuple is reported as well.
WP-3b deletes this check when the 3.8 image goes.

    python ci/check_py38_syntax.py DIR [DIR ...]
"""

import ast
import sys
from pathlib import Path


def problems(path):
    try:
        tree = ast.parse(path.read_bytes(), str(path))
    except SyntaxError as error:
        return ['{}:{}: not valid Python 3.8: {}'.format(path, error.lineno, error.msg)]
    return [
        '{}:{}: `with (a, b):` is a tuple on Python 3.8; use nested with-statements '
        'or contextlib.ExitStack'.format(path, item.context_expr.lineno)
        for node in ast.walk(tree)
        if isinstance(node, (ast.With, ast.AsyncWith))
        for item in node.items
        if isinstance(item.context_expr, ast.Tuple)
    ]


def main(dirs):
    if sys.version_info[:2] != (3, 8):
        sys.exit('run this with Python 3.8, not {}'.format(sys.version.split()[0]))
    files = sorted(f for d in dirs for f in Path(d).rglob('*.py'))
    found = [p for f in files for p in problems(f)]
    for line in found:
        print(line)
    print('{} files checked, {} problems'.format(len(files), len(found)))
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
