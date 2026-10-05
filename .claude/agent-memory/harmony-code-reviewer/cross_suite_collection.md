---
name: cross-suite-collection
description: Phase-2 suites land on separate branches; check that a new tests/ suite survives the root pytest config of sibling WPs (2a, 2f) before approving
metadata:
  type: project
---

WP-2a's and WP-2f's root `pyproject.toml` both set `testpaths = ["tests"]`. WP-2f's CI runs `uv run --locked pytest -m 'not stack'` over all of `tests/`. If a suite brings its own requirements file (WP-2d's `tests/pipeline/requirements.txt`), it breaks the root run when the two land together:
- a collection ImportError on a missing dependency (`hypothesis`);
- subprocess failures from a missing dependency (`contextlib2` under 2a's env).

**Why:** each branch passes alone. The break appears only when the second one merges, and WP files tend to defer it as a "request for WP-2f".

**How to apply:**
1. In a detached scratch worktree at the WP head, run `git checkout <sibling-branch> -- pyproject.toml uv.lock`.
2. Run `uv run pytest -q --co`, then run the new suite under that env.
3. Report any collection error as a merge-order blocker.

Related: [[ci-lint-gate]].
