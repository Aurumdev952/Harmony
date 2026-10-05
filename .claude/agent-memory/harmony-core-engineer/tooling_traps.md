---
name: tooling-traps
description: Commands that work for core checks in Harmony: multi-Python test runs, black vs ruff format, mypy flags, WP-2d pipeline suite in a scratch copy, linting with integration ruff config, proving golden cases qa owns
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
- Linting a WP branch cut before integration's ruff config: `ci/lint_python.sh` applies the full rule set (`E4,E7,E9,F,S`, format with quote-style preserve) to every changed `.py` file. Export integration's `pyproject.toml` with `git show <integration>:pyproject.toml`, rsync the worktree to /tmp, drop the file in, and run `uvx ruff@<pin> check|format` there (the old venv has no ruff). Then copy the formatted files back. Even a one-line comment edit pulls a whole legacy file into that set, with all its old F401/S101 findings, so leave untouched files out of the diff.
- Golden cases (`tests/golden/cases/**`) are qa's. To prove a new case, record it in the /tmp copy (`record.py <case>`) and hand qa the `case.json` and `request.json` through the WP Requests section.
