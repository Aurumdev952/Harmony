# 0012. Add WP-0l: match resource, role, group and user names exactly, never as patterns

Status: applied by the lead on 2026-10-06, pending human ratification (SPEC section 10).

## Context

Decision 0006 (WP-0k) removed `ILIKE` username matching from login, registration and invitation. The WP-0k QA gate noticed the same construct on resource names, and a security rating on `mig/integration` at `bc5cb2d` traced every caller of `find_one_by_fields(..., case_sensitive=False)`: `web/server/data/data_access.py:254` turns the value into `field.ilike(value)` and takes `.first()` with no ordering, so `_` and `%` in a chosen name act as wildcards and which matching row comes back is undefined. Ratings (code reading, not yet reproduced live):

| Path | Where | Outcome | Rating |
|---|---|---|---|
| A. Sharing re-finds the resource by its own name | `permission_api_models.py:201` → `resource.py:128,168` → `users.py:338`, `groups.py:172` → `core.py:61` | the route checks `update_users` on the resource in the URL but stores the ACL on whatever row the name lookup returns; dashboard names are slugified with `_`, so sharing `a_b` can grant view, edit, share or delete on `axb`, which the caller has no rights on; WP-0h's grant-subset check is not on this route | High (the WP-0l pins at `bf75d1c` show the wrong row returned before the fix) |
| B. Removing a share uses user and group names as patterns | `resource.py:112,145,152` | the removal can hit a different principal and leave the intended one with access | Medium |
| D. Group and role membership by username | `users.py:76-82` via `groups.py:250,268`, `resource.py:287` | a look-alike account joins the group or role and inherits its roles and query policy | Medium |
| H. Creation and transfer make the owner admin by re-finding the resource by name | `dashboard.py:265` (`make_author_dashboard_administrator`), `database/alerts.py:38`, `alerts.py:95` | any holder of `create_resource` on dashboard chooses the slug; with slug `a_b` while `axb` exists, the author's `dashboard_admin` ACL landed on `axb` (view, edit, delete, re-share) and the author got no admin on their own dashboard; no grant check was ever on this path; pinned by `test_creating_a_dashboard_makes_its_author_admin_of_that_dashboard`, which failed before the fix | High for dashboards; Low for alerts (names are slugified UUIDs) |
| C. ACL grants on group and user update | `grants.py:151` → `core.py:47,61` | escalation stopped by WP-0h; the 403 message repeats the matched resource's real name, so a pattern reveals names of dashboards the caller cannot list | Low |
| E. Ownership transfer by username | `dashboard.py:286`, `alerts.py:115` | transfer to or from a look-alike account | Low |
| F, G. Configuration keys; command-line scripts | `settings.py:140`, `druid_context.py:130`, `scripts/create_user.py` | fixed keys or operator-only | Low |

Found while tracing, to be confirmed by a test before they count as findings: `get_resource_by_type_and_name` (`resource.py:23-33`) combines its two conditions with Python `and`, which most likely drops the type condition; the legacy `POST /api2/{user,group}/<id>/roles` routes build `UserRoles`/`GroupRoles` with a `resource_id` the models do not have; `PATCH /roles` with an empty body strips every role.

## Decision

1. **WP-0l** (backend; supporting qa; Sec yes; depends on 0k) is added to phase 0:
   - `find_one_by_fields` with `case_sensitive=False` compares `lower(field) == lower(value)`; no caller of the data-access layer may match a name as a pattern.
   - `update_user_resource_roles` and `update_group_resource_roles` use the resource object they were given and never look it up again by name.
   - 403 bodies from `verify_acl_grants` and `try_get_role_and_resource` do not repeat resource names.
   - The three tracing notes above each get a test; whatever the tests show is fixed in this WP if it is a wrong-row or 500 outcome, or recorded.
   - qa writes the failing tests first for paths A, B and D (two dashboards whose names differ only where one has an underscore; a share removal against a look-alike; a group membership by look-alike username) and flips them on the fix branch; the WP-2b suite gains the pins.
2. **INV-3 rows** the human accepts: the ACL is stored on the resource in the URL; removing a share affects exactly the named principal; a name with `_` or `%` and no exact match returns 400 or 404 where it could resolve to another row; membership and transfers by username match exactly ignoring case; matching stays case-insensitive everywhere.
3. **Ownership.** `web/server/data/data_access.py` is core's; the one-line change there is a core request inside WP-0l, or core claims it as a supporting instance.

## Consequences

- **Amended 2026-10-06 after the WP-0l build:** row H added and row A raised to High on reproduced evidence. The fix does not move admin ACLs already stored on the wrong dashboard, including ones from innocent name matches in the past; whether to run a read-only audit per deployment (dashboards whose author lacks `dashboard_admin`; `dashboard_admin` ACLs on dashboards whose names match another's with `_` as a wildcard) is the human's call because it touches production data. INV-3 row: creating a dashboard or alert, or transferring an alert, makes the author or new owner admin of exactly that resource.

- SPEC section 5 gains the 0l row; phase 0 closes after 0j, 0k and 0l merge together.
- Security reviews the fix branch; the rating moves from code reading to live evidence there.
