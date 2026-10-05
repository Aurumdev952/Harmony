---
name: legacy-flask-test-and-lint-env
description: How to run legacy Flask/Potion tests and CI's pylint/black locally (Python 3.8 via uv, psycopg2 fails on 3.9), and harness traps in worktree-isolated sessions
metadata:
  type: reference
---

- Legacy web tests and CI's pylint need the pinned stack: build `/tmp/wp0h-reqs.txt` with the sed/grep line in WP-0h.md "How to run the tests", then `uv run --no-project -p 3.8 --with-requirements ... --with 'pytest<8' --with 'bcrypt<4.1'`. Use `-p 3.8`, not 3.9: on 3.9 psycopg2 builds from source and fails (no libpq headers).
- CI lint (`.github/workflows/integration.yml`) runs on **changed files only**: black 22.6.0 `-S -t py39 --check`, and pylint 2.17.4 that fails on any **error** (E1101 on `Model.query` is the usual one). Touching a legacy file pulls in its pre-existing errors too. Fix them or add the local `# pylint: disable=no-member` the codebase already uses. Run black with `uvx --from 'black==22.6.0' --with 'click<8.1' black`.
- The worktree-isolation hook refuses git aimed at another worktree. It also refuses compound commands it cannot parse (heredoc python plus grep, `sed ...r file`, `cd X && bash script`, variables in paths). Use one plain command per call, the Edit tool, or a script file run with `uv run --no-project python /tmp/x.py`. Bare `python3` is shimmed to demand `uv run python`.
- To compare against a base revision without touching the worktree: `git archive <rev> -o /tmp/x.tar`, extract it to /tmp, copy the test dir in. If the target directory does not exist, `cp -r` lands one level too high.

Related: [[narrowed-admin-tokens]]

Superseded once a branch merges WP-2f (mig/integration 4be8451): CI is `ci/lint_python.sh <base>` (ruff on changed files), `uv run --locked mypy`, `ci/pytest_suites.sh`. A suite that builds a Flask app and registers Potion resources must be its own top-level `tests/<name>/` directory; nested under `tests/web` it broke `test_graphql_endpoint_removed.py` by sharing the process (WP-0h, 2026-10-05). See [[post-wp2f-tooling]].
