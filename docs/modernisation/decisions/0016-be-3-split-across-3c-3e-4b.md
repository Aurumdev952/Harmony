# 0016. BE-3: what each of WP-3c, 3e and 4b delivers

Status: applied by the lead on 2026-10-06, pending human ratification (SPEC section 10).

## Context

BE-3 says database access goes through `harmony.core.db` in the SQLAlchemy 2 `select()` style, and names WP-3c, 3e and 4b. The WP-3c reviewer (round 1, c5d8c531) found the WP claims BE-3 while converting six helpers, with 16 `Model.query` call sites, about 35 `session.query(...)` calls and `find_all_by_fields` (a `Query` returned to more than 100 callers) still in place, and no owner named for the remainder. The same split was made for BE-2 under decision 0008.

## Decision

1. **WP-3c** delivers the SQLAlchemy 1.4 upgrade with 2.0 deprecations as errors in every suite, the data-access helpers it already converted, and a "BE-3 status: partial" table in its WP file that lists every remaining group with its target WP. It does not claim BE-3 complete.
2. **WP-3e** (SQLAlchemy 2.1) converts the core ORM helpers and `find_all_by_fields`'s callers in core-owned paths (`models/`, `db/`, `web/server/data`, seed scripts), pins the Potion behaviours 3c recorded (row access by string key; create relying on the backref cascade), and removes the two warning exemptions when Flask-Potion and Flask-User leave in phase 5 or earlier.
3. **WP-4b** (`harmony.core.db`) owns the session and engine layer: every remaining `session.query` moves behind `harmony.core.db` there.
4. **Phase 5** (5a to 5f) converts the `Model.query` sites in backend routes and Potion resources as each domain router is ported; BE-3 is marked done when 4b and the last 5x WP close.

## Consequences

- SPEC BE-3 row: WP column reads "3c (1.4, partial), 3e, 4b, 5a to 5f".
- The reviewer's finding 3 on WP-3c is satisfied by the status table plus this decision; the gate does not require BE-3 complete for 3c.
