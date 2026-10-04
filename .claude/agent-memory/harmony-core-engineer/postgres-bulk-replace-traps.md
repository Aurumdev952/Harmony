---
name: postgres-bulk-replace-traps
description: Traps when replacing catalogue table contents in Postgres (self-serve import, any staged upsert or data migration); cascade order, setval, test fixtures
metadata:
  type: project
---

Replacing rows in Harmony's catalogue tables, which have ON DELETE CASCADE dependents (F13, WP-2c, 2026-10-04):

- **Upsert before deleting absent rows.** If you delete first, the target rows still hold their old FKs. Deleting an old parent then cascades into rows the archive carries, and from there into their dependents. Self-references (`category.parent_id`) do this too.
- **`setval` is not transactional.** Set sequences last, and never lower them (`GREATEST(last used, max(id)) + 1`), or a rollback leaves the next insert reusing a live id. A deferred constraint trigger is a cheap way to inject a COMMIT failure in a test.
- **Tables nothing references** (mapping tables with drifting serial ids and a unique pair) are safer emptied and reloaded than upserted on `id`.
- **DELETE, not TRUNCATE, inside a long transaction.** TRUNCATE holds ACCESS EXCLUSIVE until commit and blocks web readers.
- **Throwaway Postgres for tests:** `tests/throwaway_postgres.py` (docker); see [[feedback_worktree_shell_guard]] for running ad-hoc scratch containers.

**Why:** backend's first F13 patch hit the first two traps and passed its own tests.
**How to apply:** use this for WP-5g's `$ref` migration and any other staged bulk rewrite. Add a test for each trap before trusting a green suite. See [[harmony-sqlalchemy-alembic]].
