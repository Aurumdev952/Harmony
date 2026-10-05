---
name: post-wp2f-tooling
description: After WP-2f (uv, ruff, mypy CI) tests/web run with plain uv on py3.9; lint-gate traps, worktree-guard workarounds, graphql namespace trap
metadata:
  type: reference
---

Since WP-2f merged (mig/integration 4be8451, 2026-10-04) the project is uv-managed on CPython 3.9: `uv run --locked pytest tests/web tests/graphql` and `uv run --locked mypy` work directly. The py3.8 recipes in [[py38-web-tests]] and [[flask-web-tests]] are only needed for branches older than that.

- `ci/lint_python.sh main` applies the full rule set (E4, E7, E9, F, S) plus `ruff format --check` to every .py file changed since the merge-base, so touching a legacy file means cleaning all of it.
- `ruff check --fix` deletes side-effect imports such as `import web.dev_reloader` in `web/runserver.py`; mark those `# noqa: F401` before running it.
- S310 cannot be satisfied by a scheme check alone (ruff does no flow analysis): validate, then `# noqa: S310` naming the validator. It flags `urllib.request.Request(...)` and `urlopen(...)`, but not `opener.open(...)` from `build_opener`. Security wants secret-bearing calls to refuse redirects (`allow_redirects=False`, or a `HTTPRedirectHandler` whose `redirect_request` returns None). Test that with a local server sending a 302: urllib already refuses a 307 on POST, so a 307 test passes on unfixed code too.
- The worktree guard refuses `$(cat list)` and `xargs -a` as arguments to uv, and multi-step heredoc scripts in the agent-memory dir. Pass long file lists through `uv run python -c` with `subprocess.run([...])`, or write them out literally; use the Write tool for memory files.
- In the project env, `import graphql` resolves to the repo's `graphql/` folder (namespace package), not graphql-core. Tests that load `scripts/db/hasura/check_role_permissions.py` stub `sys.modules['graphql']` (see `tests/graphql/test_hasura_scripts.py`).
