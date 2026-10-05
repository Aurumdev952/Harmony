---
name: wp-2f-next
description: How Harmony's Python toolchain is wired after WP-2f (two uv lanes, generated requirements, changed-file ruff) and the traps found building it
metadata:
  type: project
---

WP-2f (branch `mig/WP-2f-uv-ruff-mypy-ci`, 2026-10-04) set up this toolchain.

**Two Python lanes until WP-3b:**
- Root `pyproject.toml` and `uv.lock` give the app's lane: CPython 3.9, CPython-only lock.
- `ci/tools313` gives the 3.13 lane for the PEP 723 tools and `tests/infra`.
- `tests/infra/conftest.py` stops the 3.9 run collecting `tests/infra`.

WP-3b collapses the lanes with two changes:
- set `requires-python` to `"==3.13.*"` and re-lock;
- delete `ci/tools313` and the conftest guard.

**Why:** the web image is CPython 3.8, the pipeline image installs into a PyPy venv, and the newer tools target 3.13.

**How to apply:**
- `requirements*.txt` are generated verbatim from `pyproject.toml` by `docker/export_requirements.py` (`make requirements`). Never edit them by hand. A test fails on drift.
- Lock-only overrides (`psycopg2-binary` 2.8.6) do not reach the images.

**Traps**
- The `pytest-selenium` 4.0.1 dev pin crashes pytest 8 on any test failure (INTERNALERROR, exit 3, failing test hidden). Keep `-p no:selenium`.
- `pytest-flask` (dev pin) auto-pushes a request context around any test with an `app` fixture, which leaked Flask-Login state into `tests/web`. Keep `-p no:flask`. When a suite passes on a branch's own environment but fails under the full dev group, suspect auto-loaded pytest plugins first.
- ruff ignores `# pylint: disable` comments.
- ruff format is black 24 style, so a touched legacy file gets a whole-file reformat. The lead was asked for one repo-wide format commit.
- `uv pip` is blocked by a hook; use a small uv project to lock tool sets instead.
- mypy run from the repo root needs `explicit_package_bases`, because the root has an `__init__.py`.
- Security wants build tools locked as well as runtime packages. Find them with a fresh-cache `UV_CACHE_DIR=<new> UV_PROJECT_ENVIRONMENT=<new> uv sync --locked -v` and grep `Installing build requirement:`. Pin each one in `[tool.uv] build-constraint-dependencies`. A new sdist dependency can bring in a new build requirement, so re-run that check whenever the lock gains source builds.
- Diff changed files against the merge-base (`git diff --merge-base <base>`), not two-dot: a moved base otherwise lints and `--fix`es files the branch never touched. Use `-z` with `core.quotePath=false` and a `read -d ''` loop (macOS bash 3.2 has no mapfile), and put `--` before file lists.
- ruff `S`: ignore S603 and S607 (they fire on every subprocess call); in tests, ignore S101 and S311.
- To prove "a broken case turns CI red", break one case per suite. A break that touches nothing a test pins stays green: renaming a format tag no offline test covers did exactly that.
- `CI=true` changes pipeline-suite behaviour (a Hypothesis profile plus one extra test). Set it when replaying CI locally.

Related: [[ci-tooling-and-guards]].
