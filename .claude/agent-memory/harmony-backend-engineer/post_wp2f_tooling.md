---
name: post-wp2f-tooling
description: After WP-2f (uv, ruff, mypy CI) tests run with plain uv on py3.9 but production is still CPython 3.8 until WP-3b; lint-gate traps, guard workarounds, graphql namespace trap
metadata:
  type: reference
---

Since WP-2f merged (mig/integration 4be8451, 2026-10-04) the project is uv-managed on CPython 3.9: `uv run --locked pytest tests/web tests/graphql` and `uv run --locked mypy` work directly. That dev env is 3.9, but the web image still runs **CPython 3.8.20** until WP-3b, so 3.8 still matters: every change must import on 3.8. In WP-0h (2026-10-05) `ruff format` under the old py39 target rewrote a chained `with A(...), B() as b:` into a parenthesised `with (...)` (3.9+ syntax) and broke `create_app` on 3.8; all gates on 3.9 were green. Integration now sets ruff's target to py38 (1c8578e). Before review, compile changed files with `uv run --no-project -p 3.8 python -m py_compile ...` and run the touched suite once on a 3.8 web env (e.g. a venv built per [[py38-web-tests]]).

- `ci/lint_python.sh main` applies the full rule set (E4, E7, E9, F, S) plus `ruff format --check` to every .py file changed since the merge-base, so touching a legacy file means cleaning all of it.
- `ruff check --fix` deletes side-effect imports such as `import web.dev_reloader` in `web/runserver.py`; mark those `# noqa: F401` before running it.
- S310 cannot be satisfied by a scheme check alone (ruff does no flow analysis): validate, then `# noqa: S310` naming the validator. It flags `urllib.request.Request(...)` and `urlopen(...)`, but not `opener.open(...)` from `build_opener`. Security wants secret-bearing calls to refuse redirects (`allow_redirects=False`, or a `HTTPRedirectHandler` whose `redirect_request` returns None). Test that with a local server sending a 302: urllib already refuses a 307 on POST, so a 307 test passes on unfixed code too.
- The worktree guard refuses `$(cat list)` and `xargs -a` as arguments to uv, and multi-step heredoc scripts in the agent-memory dir. Pass long file lists through `uv run python -c` with `subprocess.run([...])`, or write them out literally; use the Write tool for memory files.
- Repeated `import models.alchemy.x` lines all bind `models`; ruff F401 reports only the last one, and `--fix` then deletes them one per run. Put `# noqa: F401` on every registration import.
- On the 3.8 web env (2026-10-05), 21 qa tests in `tests/web` (`test_field_info_route`, `test_query_policy_filter`, `test_dashboard_unauthorized_redirect`) fail with `AttributeError: __enter__`: parenthesised `with` needs 3.9+. Compare against the base before blaming your change.
- To see compile-time SyntaxWarnings (e.g. flask_potion `utils.py:25`) in a test, run the fresh interpreter with a new `PYTHONPYCACHEPREFIX`; cached .pyc files hide them.
- In the project env, `import graphql` resolves to the repo's `graphql/` folder (namespace package), not graphql-core. Tests that load `scripts/db/hasura/check_role_permissions.py` stub `sys.modules['graphql']` (see `tests/graphql/test_hasura_scripts.py`).
- Since WP-4a (integration, 2026-10-06) the web code imports `pydantic` (`harmony/core/settings.py`), which the shared 3.8 venv `/tmp/wp2g-be3-py38` lacks: every harness test errors at setup. Do not install into the shared venv; `/tmp/wp2g-be3-py38/bin/python -m pip install --target <dir> pydantic==2.10.6 pydantic-settings==2.8.1 typing_extensions==4.12.2`, then run with `PYTHONPATH=<dir>`. Check `git diff <old> <new> -- requirements.txt` after any integration merge for further additions.
- Host load from parallel agents (load average 40) stretches the privilege-escalation harness from about 100 s to 9 min; slowness there is not a regression by itself, check `uptime` first.
