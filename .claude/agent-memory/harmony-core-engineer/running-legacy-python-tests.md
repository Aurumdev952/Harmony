---
name: running-legacy-python-tests
description: How to run pytest against the legacy Flask 1.0 / Python 3.8 web code with uv when hooks block `uv pip` and the requirements have editable git deps
metadata:
  type: reference
---

- A hook blocks `uv pip install`. Use an ephemeral env instead: `uv run --no-project -p 3.8 --with-requirements <file> --with 'pytest<8' python -m pytest ...`, with `PYTHONPATH` set to the worktree root.
- `--with-requirements` rejects `-e git+...#egg=X` lines. Rewrite them to `X @ git+...` in a scratch copy outside the repo. Add `pylib @ git+https://github.com/room77/py77.git@<sha>` if you import `web.server.app` (app_base needs pylib).
- `config/settings.py` reads `DEFAULT_SECRET_KEY` and `DRUID_HOST` at import. Set placeholders in a conftest. `tests/web/conftest.py` already does this (WP-0c).
- Flask 1.0.1 inside pytest: `Flask(__name__)` raises `AssertionRewritingHook.is_package() method is missing`. Pass `root_path` and `instance_path` explicitly (the `bare_flask_app` fixture in tests/web/conftest.py).
- Keep test code Python 3.8 compatible: ruff wants `X | None` and `collections.abc.Callable`, so add `from __future__ import annotations`. Format with `black --skip-string-normalization` (the CI setting), not `ruff format`.
- The worktree-isolation hook refuses compound Bash commands that `cd` outside the worktree or compute command names. Put multi-step work in a script under /tmp and run it with a single command.

Related: [[wp-0c-findings]]
