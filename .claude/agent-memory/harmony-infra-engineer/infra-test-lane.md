---
name: infra-test-lane
description: tests/infra runs only on the 3.13 tools project; the default uv env is CPython 3.9 and lacks tomllib
metadata:
  type: project
---

Run `tests/infra` with `uv run --project ci/tools313 --locked pytest tests/infra`, as CI (`integration.yml`) and `make test` do. Plain `uv run pytest tests/infra` uses the root lock's CPython 3.9 and fails at collection with `No module named 'tomllib'`.

**Why:** the root project still targets py38/py39 for the legacy images. Infra tests use 3.11+ stdlib.

**How to apply:** use the tools313 lane for any infra test run. For a test-first proof when the change is a coupling assertion that already holds on the tree, mutate the Dockerfile in place, run the test, then restore it from a /tmp copy. Record each failure message as evidence.

`ownership.py` must also be run through `uv run python` (the hook refuses `python3`). The worktree guard refuses long multi-statement Bash heredocs that edit files, so use the Edit tool for WP-file edits.
