# 0001. Tests are shared by role; WP-0c belongs to backend

Status: applied by the lead on 2026-10-04, pending human ratification (SPEC section 10). Object before merging any `mig/*` branch if you disagree.

## Context

The first wave exposed two ownership gaps:

1. `tests/**` was owned by `qa` alone. SPEC requires every bug fix to start with a failing test, and section 8 requires unit tests per unit, so no builder could satisfy the definition of done without a request to qa for every test file. The hook blocked `core-1` from adding regression tests for WP-0c.
2. WP-0c (pure-mistake bugs) was assigned to `core`, but every file it changes is owned by another role: `web/server/routes/dashboard.py`, `web/server/util/util.py` and `web/server/routes/views/query_policy.py` are `backend`; `docker-compose.pipeline.yaml` is `infra`.

## Options

- Grant one-off exceptions. Rejected: the lead skill forbids it and the hook cannot express it.
- Route every test through qa. Rejected: qa becomes a serial bottleneck for every WP.
- Make `tests/**` shared and keep the cross-cutting suites with qa through longer prefixes. Chosen.
- Keep WP-0c with core and have core send patches to backend. Rejected: two agents for one small WP.

## Decision

1. `tests/**` moves to the `shared` row. `qa` keeps `tests/golden/**`, `tests/authz/**`, `tests/contract/**`, `tests/pipeline/**` and `tests/conftest.py`, which win by longest literal prefix. Builders add unit tests for their own code under `tests/<area>/`, for example `tests/web/` or `tests/core/`.
2. WP-0c's owner becomes `backend`, with `core` supporting (the `run_raw_query` policy decision) and `infra` supporting (the compose fix).

## Consequences

- SPEC section 6 table and the WP-0c row are edited; version bumped to 1.2.
- Builders already running must merge branch `mig/decisions-0001-ownership` so their worktree's hook reads the new table.
- `core-1`'s analysis and failing tests for WP-0c are handed to the backend builder on the same branch.
- `scripts/agents/ownership.py` now scores the `shared` row like any other row (longest literal prefix wins) instead of short-circuiting, so `tests/golden/**` stays with qa while `tests/**` is shared.
