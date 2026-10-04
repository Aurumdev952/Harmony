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
- ruff ignores `# pylint: disable` comments.
- ruff format is black 24 style, so a touched legacy file gets a whole-file reformat. The lead was asked for one repo-wide format commit.
- `uv pip` is blocked by a hook; use a small uv project to lock tool sets instead.
- mypy run from the repo root needs `explicit_package_bases`, because the root has an `__init__.py`.

Related: [[ci-tooling-and-guards]].
