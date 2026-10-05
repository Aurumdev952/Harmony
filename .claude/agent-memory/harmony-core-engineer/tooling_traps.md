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
- Image-runtime test runs (WP-4a): CPython 3.8 works with `uv run -p 3.8 --no-project --with-requirements <scratch requirements.txt> --with-requirements <scratch requirements-web.txt> ...`, after rewriting each `-e git+URL@sha#egg=X` line to `X @ git+URL@sha`. PyPy 3.8 with `requirements-pipeline.txt` does not build locally (numpy 1.15.4 sdist), so smoke-import there with only the new pins.
- Blocking network in a test subprocess: patch `socket.socket.connect`, `connect_ex` and `sendto`, plus `socket.create_connection` and `socket.getaddrinfo`. Replacing `socket.socket` itself breaks `import ssl`, which subclasses it; pydantic-settings pulls `ssl` in through asyncio.
- import-linter (dev only, needs Python >= 3.9) prints ANSI colours even when piped, so strip `\x1b\[[0-9;]*m` before asserting. With only `harmony.core` as root package, legacy packages are opaque leaves. List them in `root_packages` to catch transitive imports (872 files take 0.4 s).
- pydantic-core 2.27.2 (pydantic 2.10.6) has PyPy 3.9 wheels. Only later pydantic-core releases dropped them.
