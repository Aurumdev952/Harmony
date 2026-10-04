---
wp: "2a"
title: "Golden query suite"
status: building
owner_role: "qa"
instances:
  - name: "qa-1"
    files: ["tests/golden/**", "tests/conftest.py", "docs/modernisation/work/WP-2a.md"]
branch: "mig/WP-2a-golden-query-suite"
requirements: [QA-4]
contracts_consumed: [C-3]
contracts_changed: []
security_review: false
---

# WP-2a: Golden query suite

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Environment: minimal root `pyproject.toml` with a `golden` dependency group (the query engine's import closure at the pins in `requirements*.txt`) on CPython 3.9 (the interpreter in `docker/dev/Dockerfile`), plus `uv.lock`. Check: `uv sync` and every query and visualization module imports inside a bare Flask app context.
2. Harness: `tests/golden/harness.py` (bootstrap a bare Flask app with the `harmony_demo` config, a fixed `DruidApplicationContext` stand-in, a recording `DruidQueryClient_` that intercepts `run_raw_query`, the HTTP boundary) and `tests/golden/test_golden.py` that replays every case directory. Check: a hand-written smoke case passes; a mutated `druid_query.json` and a mutated `expected_response.json` each turn it red.
3. Recorder: `tests/golden/record.py` regenerates `druid_query.json`, `druid_response.json` and `expected_response.json` from `request.json` plus `case.json` (endpoint, policy, extra args), synthesising deterministic Druid rows with `harmony_demo` dimension values. Check: running it twice gives byte-identical fixtures, also under different `PYTHONHASHSEED`s.
4. Cases: one per visualization endpoint (`bar_graph`, `line_graph`, `hierarchy`, `map`, `table`, `table/disaggregated`) and per frontend visualization type that reshapes the request; one per calculation type (SUM, COUNT, AVG, MIN, MAX, FORMULA, COUNT_DISTINCT, COMPLEX, LAST_VALUE, AVERAGE_OVER_TIME, WINDOW, COHORT); grouping by dimension, by every granularity, by granularity extraction, with subtotals; every filter type (AND, OR, NOT, SELECTOR, IN, FIELD, FIELD_IN, INTERVAL, RAW); query-policy variants (none, simple, hierarchical, complex, all values). Check: `uv run pytest tests/golden` green in under 60 s.
5. Docs: `tests/golden/README.md` (what is pinned, how to run, when regeneration is allowed: only with an INV-2 note in the WP file). Check: README commands copy-paste and pass.
6. Self-verify: deliberately broken builder and shaping edits turn the suite red; record evidence; status review.

## Contract changes

None. This WP only reads the current query engine.

## Requests

## Log

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
