---
wp: "2f"
title: "uv, ruff, mypy, CI running every suite"
status: building
owner_role: "infra"
instances:
  - name: "infra-2"
    files:
      - pyproject.toml
      - uv.lock
      - requirements*.txt
      - mypy.ini
      - .pylintrc
      - .dockerignore
      - docker/export_requirements.py
      - tests/infra/test_requirements_export.py
      - .github/workflows/integration.yml
      - .github/dependabot.yml
      - Makefile
branch: "mig/WP-2f-uv-ruff-mypy-ci"
requirements: [SEC-9, QA-4, INV-8]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-2f: uv, ruff, mypy, CI running every suite

Phase detail: `docs/modernisation/phase-2-test-harness-and-toolchain.md` section 2f. Branched from `mig/integration`. The starting point is WP-2a's minimal `pyproject.toml` (`mig/WP-2a-golden-query-suite`).

## Plan

Units, in order. Each line names the change and the check that ends it.

1. **`pyproject.toml` and `uv.lock` become the source of truth for Python dependencies.**
   - `requirements.txt` becomes `[project].dependencies`.
   - `requirements-web.txt`, `requirements-pipeline.txt` and `requirements-dev.txt` become the dependency groups `web`, `pipeline` and `dev`.
   - Today's pins are kept as they are.
   - The lock is for CPython 3.9, the CI and dev interpreter. Moving to 3.13 means changing `requires-python` and re-locking (WP-3b).

   Check:
   - `uv lock` succeeds, and `uv sync --locked` builds the environment;
   - `uv run pytest` passes;
   - WP-2a's golden suite passes under this environment.
2. **`requirements*.txt` are generated from `pyproject.toml`** by `docker/export_requirements.py` (`make requirements`). The images keep `pip install -r` until WP-3b switches them to uv. Check:
   - every generated file has the same set of requirement lines as today's hand-written file, so the image inputs do not change;
   - `tests/infra/test_requirements_export.py` fails when they drift.
3. **ruff replaces black and pylint.**
   - Configuration lives in `pyproject.toml`.
   - Formatting matches black: line length 88, quote style preserved.
   - Lint runs repo-wide with a rule set the tree passes today.
   - `.pylintrc` is deleted, and black and pylint leave the `dev` group.
   - The Makefile lint targets call ruff.

   Check: `uv run ruff check .` exits 0, and `ruff format --check` passes on a file that black accepted.
4. **mypy configuration moves into `pyproject.toml`** (`mypy.ini` is deleted), with the same files, plugin and per-module overrides. Check: `uv run mypy` gives the same result as `mypy --config-file mypy.ini` before the move.
5. **`integration.yml` runs the toolchain on every PR:**
   - `uv lock --check` and `uv sync --locked`;
   - `ruff check`, and `ruff format --check` on changed files;
   - mypy;
   - `pytest` over `tests/`, so new suites run without a workflow change. Suites that need the compose stack are marked `stack` and deselected.

   Every action is pinned by SHA, and every grant follows WP-0f. Check:
   - actionlint reports 0;
   - the WP-0f policy script passes;
   - the job's commands pass locally;
   - a deliberately broken test makes the pytest command exit non-zero.
6. **Dependabot** covers `github-actions` and `uv`. Check: `check-jsonschema --builtin-schema vendor.dependabot` passes.

## Contract changes

None.

## Requests

## Log

## Decisions

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
