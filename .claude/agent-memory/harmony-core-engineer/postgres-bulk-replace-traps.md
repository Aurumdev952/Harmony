---
name: postgres-bulk-replace-traps
description: Traps when replacing catalogue table contents in Postgres (self-serve import, any staged upsert or data migration); cascade order, setval, last_modified trigger, OIDs past 2^31, test fixtures
metadata:
  type: project
---

Replacing rows in Harmony's catalogue tables, which have ON DELETE CASCADE dependents (F13, WP-2c, 2026-10-04):

- **Upsert before deleting absent rows.** If you delete first, the target rows still hold their old FKs. Deleting an old parent then cascades into rows the archive carries, and from there into their dependents. Self-references (`category.parent_id`) do this too.
- **`setval` is not transactional.** Set sequences last, and never lower them (`GREATEST(last used, max(id)) + 1`), or a rollback leaves the next insert reusing a live id. A deferred constraint trigger is a cheap way to inject a COMMIT failure in a test.
- **Tables nothing references** (mapping tables with drifting serial ids and a unique pair) are safer emptied and reloaded than upserted on `id`.
- **DELETE, not TRUNCATE, inside a long transaction.** TRUNCATE holds ACCESS EXCLUSIVE until commit and blocks web readers.
- **Catalogue tables carry `update_last_modified`** (migration 2b730c14f514), a BEFORE UPDATE trigger that sets `last_modified = now()` with no condition. Any UPDATE, even an upsert or a follow-up `SET last_modified = ...`, overwrites the value, and the self-serve validator reads it for conflict detection. Skip unchanged rows (`DO UPDATE ... WHERE ROW(t.c::text, ...) IS DISTINCT FROM ROW(EXCLUDED.c::text, ...)`; cast to text because json has no `=`). Run the write with `ALTER TABLE ... DISABLE TRIGGER update_last_modified`, which is transactional and needs ownership (security N1, 2026-10-05).
- **`ALTER TABLE ... ENABLE TRIGGER` fails while the table has deferred trigger events pending.** Re-enable before writing to any table that has a deferred constraint or trigger, or do not disable the trigger on that table at all.
- **`create_all` test schemas have no migration triggers.** A test of how a write affects `last_modified` must install them. `tests/db` runs the migration's `upgrade()` with `op` stubbed to `SimpleNamespace(execute=cursor.execute)`. N1 went unseen for a full review round because of this.
- **Never read an OID as `::integer`.** OIDs are unsigned 32-bit and the counter is cluster-wide (temp tables, TOAST), so long-lived clusters pass 2^31 and the value goes negative; ` -123::oid::regclass` then fails with `operator does not exist: - regclass`. Bind the quoted name (`sql.Identifier(...).as_string(cursor)`) with `%s::regclass` instead (reviewer round 7, 2026-10-05). Test it with `postgres_server` parametrized indirectly with a next OID: the image's entrypoint cannot run `pg_resetwal`, so that path runs `initdb` itself as user postgres, then `pg_resetwal --next-oid`, then `postgres`.
- **Throwaway Postgres for tests:** `tests/throwaway_postgres.py` (docker); see [[feedback_worktree_shell_guard]] for running ad-hoc scratch containers.

**Why:** backend's first F13 patch hit the first two traps and passed its own tests.
**How to apply:** use this for WP-5g's `$ref` migration and any other staged bulk rewrite. Add a test for each trap before trusting a green suite. See [[harmony-sqlalchemy-alembic]].
