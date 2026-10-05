---
name: tooling-traps
description: Lint-gate and suite-check commands for qa after WP-2f; golden --check, expected pipeline skip, ruff format on py39
metadata:
  type: reference
---

- `ci/lint_python.sh main` lints every file changed since the merge-base, other roles' files included. Scope it with `uv run --locked ruff check` and `ruff format --check` on your own paths.
- The golden "zero fixture changes" check is `uv run python tests/golden/record.py --check`. It prints `N cases, 0 fixture files would change`.
- `tests/pipeline/test_properties.py` skips outside the CI profile, so one skip in `pytest tests/golden tests/pipeline` is expected.
- `ruff format` rewrites chained `with a(), b():` into the parenthesized form even at target py39. CPython 3.9's parser accepts it, but rerun the suite on 3.9 to prove it.
- See [[worktree-guard-bash]] for the commands the isolation guard refuses.
