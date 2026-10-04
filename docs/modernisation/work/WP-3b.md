---
wp: "3b"
title: "One CPython 3.13 interpreter everywhere"
status: claimed
owner_role: "infra"
instances:
  - name: "infra-3"
    files:
      - pyproject.toml
      - uv.lock
      - requirements*.txt
      - docker/**
      - docker-compose*.yaml
      - .dockerignore
      - Makefile
      - ci/**
      - .github/workflows/**
      - tests/infra/**
      - tests/toolchain/**
      - docs/modernisation/work/WP-3b.md
branch: "mig/WP-3b-cpython-313"
requirements: [INV-1, INV-2, INV-8, SEC-9, QA-4]
contracts_consumed: []
contracts_changed: []
security_review: false
---

# WP-3b: One CPython 3.13 interpreter everywhere

Phase detail: `docs/modernisation/phase-3-python-and-dependency-floor.md` section 3b. Branched from `mig/integration` at `15bdde3`, which carries WP-3a (the `find_spec` config hook) and WP-2f (uv, ruff, mypy, the two CI lanes).

## Plan

Units, in order. Each line names the change and the check that ends it.

1. **The root lock moves to CPython 3.13.** `requires-python = "==3.13.*"`; every pin that has no CPython 3.13 build or fails at import on 3.13 moves to the lowest release that works; PyPy markers and the PyPy numpy pin go; `[tool.uv] environments` and the lock-only psycopg2 override go; build constraints are re-derived from a fresh-cache sync. Check: `uv lock --check`; fresh-cache `uv sync --locked`; an import sweep of every first-party module on 3.13 matches the 3.9 sweep; every suite under `tests/` passes on 3.13, golden with `record.py --check` at 0 drift and the pipeline suite at 130.
2. **One CI lane.** `ci/tools313` and the `tests/infra` conftest guard are deleted; `tests/infra` joins `ci/pytest_suites.sh`; the strict mypy check of the standalone tools moves into the root config; `integration.yml` has one Python 3.13 job; uv moves to a release that hashes build-tool entries (0.12.16 or later); `make test` follows. Check: actionlint, zizmor, the WP-0f policy script, and the job's commands locally, with one broken case making it exit non-zero.
3. **Web image on `python:3.13-slim-bookworm` with uv.** Multi-stage: `uv sync --locked --no-install-project` then the app; runtime stage holds `.venv` and the app, running as a non-root user. One image serves web and worker. Check: `docker build --check`; the image builds; an import sweep inside it; `docker compose config --quiet` for every overlay; the web and worker containers start against the compose stack and the web healthcheck passes.
4. **Pipeline image on CPython 3.13 with uv, no PyPy.** The PyPy venv goes; `SetupEnvForPyPy` already falls back to the active venv when `venv_pypy3` is absent, so pipeline steps run on CPython with no pipeline-owned change. Check: the image builds; the pipeline fixture suite passes inside it; a `harmony_demo` step runs; wall-clock of the pipeline suite on CPython 3.13 against PyPy 3.9 recorded.
5. **Dev image on CPython 3.13.** The Python 3.9 source build and the PyPy download go; the dev Compose overlay drops the `venv_pypy3` volume. Check: the image builds; `make up DEV=1` brings up web with the dev overlay.
6. **Image workflows.** The image tag is sanitised for branch names containing `/` (WP-0f leftover). Check: actionlint and a simulated `run:` with `mig/WP-3b-cpython-313`.

## Contract changes

None.

## Requests

None yet.

## Log

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
