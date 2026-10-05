---
name: tooling-traps
description: Commands that work for core checks in Harmony: multi-Python test runs, black vs ruff format, mypy flags, WP-2d pipeline suite in a scratch copy
metadata:
  type: reference
---

Shell-guard and `python3` workarounds are in [[worktree-shell-guard]].

- Bare interpreters do not see the repo: add `PYTHONPATH=.` for `uv run --no-project` (the root pyproject sets pytest `pythonpath` only).
- Multi-version runs: `uv run -q -p {3.8,3.9,3.11,3.13,pypy3.9} --no-project --with pytest pytest -p no:cacheprovider tests/core`. All of those interpreters are installed locally.
- black 22.6 (`-S -t py39`) and ruff format (quote-style preserve) disagree on `assert cond, msg` that wraps, and on a blank line after a module docstring. Keep the assert on one line (use a message variable) and put a blank line after the docstring; then both pass.
- mypy as WP-2f pins it: `uv run -p 3.9 --no-project --with mypy==1.3.0 --with sqlalchemy-stubs==0.4 mypy --follow-imports=silent <files>`. Without `--follow-imports=silent`, errors from untouched imported files (`config/*/general.py`, requests stubs) show up.
- WP-2d pipeline suite: overlay `git archive <branch> tests/pipeline` onto a `git archive HEAD` copy in /tmp, then `CI=1 [PIPELINE_FIXTURE_PYTHON=3.13|pypy3.9] tests/pipeline/run.sh -q`. Re-check the suite branch revision before comparing before and after, because it moves.
- The session caps concurrent subagents at 20; when `pstack:how` cannot spawn explorers, do the exploration inline and say so in the WP file.
- Checking whether pins have CPython 3.13 wheels: `uv pip install --dry-run --python-version 3.13 --python-platform x86_64-manylinux_2_28 --only-binary :all: --target /tmp/x "<pin>"`, one pin at a time, because the resolver stops at the first failure.
- The web image runs CPython 3.8.20, even though `requires-python` says 3.9. Prove Python syntax on 3.8: `uv run --no-project -p cpython-3.8.20 python -m py_compile <f>` and `... python ci/check_py38_syntax.py <dir>`. An AST check under the project's 3.9 venv is not enough, because 3.9 accepts parenthesised `with`. In WP-2c, `bc8ad57` broke `create_app` that way. Ruff now targets py38, but ruff format does not undo a parenthesised `with` that already exists. Restore the chained form by hand (or from the pre-format revision), then format. `ci/lint_python.sh <base>` format-checks every changed `.py`, including files other roles merged into the branch.
- Do not apply ruff's E712 fix (`not Col`) to SQLAlchemy column comparisons, because `not` breaks the SQL. Use `Col.is_(False)` instead.
