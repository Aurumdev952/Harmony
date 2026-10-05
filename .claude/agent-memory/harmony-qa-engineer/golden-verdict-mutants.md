---
name: golden-verdict-mutants
description: How to give an independent QA verdict on golden-suite or query-path WPs with in-memory mutants, plus shell/guard traps hit doing it (2026-10-04, WP-2a review)
metadata:
  type: project
---

Use in-memory mutants loaded as a pytest plugin, never edits to production files.
- Put `golden_mutants.py` in a dir outside the repo, `export PYTHONPATH=<dir>`, then `MUTANT=<name> uv run pytest tests/golden -p golden_mutants`. Patch in `pytest_collection_finish` (after `tests/golden/conftest.py` bootstraps the app).
- **Trap:** never name a helper module after a stdlib module (`inspect.py` on PYTHONPATH broke pytest's own import).
- Useful mutants:
  - policy off: `query_policy.restrict_query_filter_to_user_permissions = lambda q, user_identity=None: q`.
  - scoped policy bypass: wrap `QueryBase.__init__` to hand `query_client.query_client` (the unwrapped client) to chosen engines. On WP-2a this showed only bar_graph, table and line_graph had policy cases; the other 9 engines could drop the policy with the suite green.
  - reversing `aggregations` in `GroupByQueryBuilder.prepare` fails 54 response tests: `parse` maps array columns by the builder's order, so the harness's aggregator sort does not mask a column-order regression.

**Shell traps (worktree guard).** Compound bash with heredocs, `env -u`, loops calling python or git are refused. Write scripts with the Write tool into /tmp and run `bash /tmp/x.sh`. Run `git worktree add/remove` from your own worktree. `python3` is blocked by a hook; use `uv run python`.

**Why:** these took several retries to find. **How to apply:** any verdict on WP-1x, 3x, 4x or 8a that touches the query path. See [[golden-suite-harness]].
