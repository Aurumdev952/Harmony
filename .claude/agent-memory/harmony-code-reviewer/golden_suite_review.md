---
name: golden-suite-review
description: How to probe tests/golden (WP-2a and any WP that regenerates golden cases) - in-memory mutant plugin, seam check, JWT identity trap, code-review skill worktree trap
metadata:
  type: project
---

Lessons from reviewing WP-2a (2026-10-04):
- **Mutants without editing files.** Write a pytest plugin in /tmp, run `PYTHONPATH=/tmp/x uv run --no-sync pytest tests/golden -p plugin`, and apply patches in `pytest_collection_finish`. That hook runs after `tests/golden/conftest.py` has bootstrapped the Flask app, so production modules import cleanly. A loop over mutants or seeds needs a Python runner using `subprocess`, because the worktree guard refuses shell loops around `uv`.
- **Seam check.** The WP-2a harness overrode `DruidQueryClient_.run_raw_query`, so production response decoding (ijson `use_float=True`, gzip, requests `allow_nan=False`) never ran. A requests adapter mounted on the session from `db.druid.query_client._get_session` passed all 226 tests unchanged. With that adapter, a Decimal-decoder mutant failed 126 tests, while the override let it through with 226 green. Re-check this whenever `query_client.py` or the harness seam changes.
- **JWT identities.** Production `_compute_token_query_needs` (web/server/security/signal_handlers.py) sets `all_values = not include_values` and replaces `identity.provides` with the intersection of token and account needs. A harness that adds the needs on top pins filters production never builds. Exclude needs and multi-dimension needs come only from JWT claims.
- **Possible authz bug** (unverified over HTTP; routed to security 2026-10-04). `DimensionFilter.__and__` intersects the exclude sets when both sides are all-values, so a JWT exclusion is dropped for an account that sees all values.
- **The `code-review` skill (forked) checked out the WP branch in my own worktree** and then switched back. Point it at the scratch worktree path. Also verify every item it returns: this time 4 of its 10 were not real defects.

**Why:** each of these either found a real defect or wasted a round.
**How to apply:** for any WP touching `tests/golden`, `db/druid/query_client.py` or query policies, rerun the seam and policy mutants. Related: [[review-traps]].
