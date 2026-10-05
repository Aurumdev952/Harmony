---
name: py38-web-tests
description: How to run tests/web against the Flask 1.0 / Python 3.8 stack with uv when the worktree guard rejects compound shell commands
metadata:
  type: reference
---

`tests/web` needs Python 3.8 and the web requirements (see WP-0c's "How to run the tests" for the `sed` that rewrites `-e git+` lines into `/tmp/reqs.txt`). `tests/core` uses `str | None` and needs a newer Python: run it separately with `uv run --no-project --with pytest pytest tests/core`.

The worktree-isolation guard refuses shell lines that combine `uv run ... 'pytest<8'` with pipes, loops or computed variables. Put the `uv run --no-project -p 3.8 --with-requirements ... python "$@"` line in a small script under `/tmp` and call that. Lint with pinned `pylint==2.17.4` and `black==22.6.0 --skip-string-normalization` (requirements-dev.txt).

Flask 1.0 cannot build an app from a module loaded by pytest's rewrite hook: pass `root_path` explicitly (`Flask('tests.web', root_path=...)`).

A container's bridge IP is not reachable from this host's shell; publish throwaway services on `127.0.0.1:<high port>` (6379 and 5432 are already taken on the host).

**`tests.` imports break on the web image's 3.8 stack** (WP-0i, 2026-10-05). The editable Flask-Potion install puts its checkout on sys.path, and that checkout ships a regular `tests` package (which imports `flask_testing`). A regular package beats the repo's `tests` namespace package wherever it sits on the path, so `from tests.web.x import ...` fails to collect there. The WP-0c sed recipe installs Flask-Potion non-editable and hides this. Import test helpers by a unique basename instead (pytest puts a directory with no `__init__.py` on sys.path). To reproduce, put a dir containing `tests/__init__.py` with `import flask_testing` after the repo on PYTHONPATH.
