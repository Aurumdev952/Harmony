---
name: wp-2f-next
description: How Harmony's Python toolchain is wired after WP-3b (one 3.13 lane, uv >= 0.12.16, no requirements files) and the traps found building it
metadata:
  type: project
---

WP-2f (2026-10-04) set up uv, ruff, mypy and CI. WP-3b (branch `mig/WP-3b-cpython-313`, 2026-10-05) folded the two lanes into one.

**After WP-3b:**
- There is one root `pyproject.toml`/`uv.lock`, with `requires-python = "==3.13.*"`.
- `ci/tools313`, the `tests/infra` conftest guard, `requirements*.txt` and `docker/export_requirements.py` are gone.
- `[tool.uv] required-version = ">=0.12.16"`, because the build constraints are hashed. The build host's `uv` was 0.12.5, so every `uv` command in a checkout of the branch fails. That includes `uv run --no-project` and the hook-mandated `uv run python scripts/agents/...`. Use a 0.12.23 binary (`uvx uv@0.12.23` caches one) until the host is updated.
- The standalone tools get their strict mypy flags from a per-module override in the root config. The app is on mypy 1.3; mypy 1.11 and later find 6 or 7 errors in core/backend files.

**Traps**
- The `pytest-selenium` 4.0.1 dev pin crashed pytest 8 on any test failure. It left the lock in WP-3b.
- `pytest-flask` auto-pushes a request context around any test with an `app` fixture. Keep `-p no:flask`.
- ruff ignores `# pylint: disable`. ruff format is black 24 style. The tree is not formatted (about 270 files), so CI checks formatting on changed files only.
- `uv pip` is blocked by a hook. Use a small uv project, `uv run --with`, or `uv sync --inexact` instead.
- Security wants build tools locked with hashes: `build-constraint-dependencies = [{ requirement = "setuptools==X", hashes = [...] }]`. Find the build tools with a fresh-cache `UV_CACHE_DIR=<new> UV_PROJECT_ENVIRONMENT=<new> uv sync --locked -v` and grep for `Installing build requirement:`.
- `uv run --locked` on an older branch (requires-python 3.9) silently replaces the worktree `.venv` with a 3.9 one. Re-run `uv sync --locked` after switching back.
- Diff changed files against the merge-base, not two-dot. `CI=true` changes how the pipeline suite behaves.

Related: [[ci-tooling-and-guards]], [[image-verification-recipes]].
