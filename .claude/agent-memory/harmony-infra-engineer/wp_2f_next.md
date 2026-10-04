---
name: wp-2f-next
description: WP-2f is the infra instance's next WP after WP-0f merges; the PR lint job still runs Python 3.9 pylint/black and fails 3.13-style code
metadata:
  type: project
---

The lead assigned WP-2f (uv, ruff, mypy, CI running every suite) to this infra instance, to start right after WP-0f merges. That was 2026-10-04.

**Plan item:** replace the `lint-python` job in `.github/workflows/integration.yml` with these:
- `uv`;
- `ruff check` and `ruff format --check` on Python 3.13;
- mypy.

The job also needs to stop listing changed files through `gh pr view`. Keep the WP-0f conventions:
- SHA-pinned actions;
- `ubuntu-24.04`;
- `permissions: {}` with per-job grants;
- the token scoped to the steps that need it.

Also add Dependabot for `github-actions`.

**Why:** the job still installs CPython 3.9 and runs black `-t py39` plus pylint, so new 3.13-style code fails there. WP-0g's code is the first known case. PR #2 on Aurumdev952/Harmony also showed that every lead-owned `scripts/agents/*.py` change trips it.

**How to apply:** treat red "Python - Lint" on 3.13-style syntax as WP-2f's problem, not as a reason to downgrade code. Related: [[ci-tooling-and-guards]], [[wp-0f-open-items]].
