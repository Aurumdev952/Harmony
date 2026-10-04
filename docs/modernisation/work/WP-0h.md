---
wp: "0h"
title: "Close privilege escalations in group and role management"
status: building
owner_role: "backend"
instances:
  - name: "backend-6"
    files:
      - "web/server/api/**"
      - "web/server/security/**"
      - "web/server/potion/**"
      - "tests/web/privilege_escalation/**"
      - "docs/modernisation/work/WP-0h.md"
branch: "mig/WP-0h-privilege-escalations"
requirements: [INV-3]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0h: Close privilege escalations in group and role management

Phase detail: [phase-0-security-and-subtraction.md, section 0h](../phase-0-security-and-subtraction.md). Added by [decision 0003](../decisions/0003-wp-0h-privilege-escalations.md).

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Read the group and role Potion resources, their managers, and the permission plumbing (`pstack:how`). Check: notes in this file name the code paths behind each escalation.
2. Failing tests, one per escalation, through the real Flask app and Potion routes with constructed users. Check: the three tests fail on the integration branch for the reason the escalation gives.
3. The fix. Check: the three tests pass; existing tests for the touched area pass.
4. INV-3 difference table, plus the WP-2b pure layer run against the fix. Check: suite output recorded under Evidence.
5. `pstack:interrogate` on the fix, findings addressed, `status: review`.

### How each escalation works (unit 1)

The handlers turn caller-supplied ids into ORM objects without a filter, and every check is on the container (`create_resource`/`edit_resource` on `group` or `role`, all sitewide in the seed), never on what is granted.

1. **`POST /api2/group`** (`GroupResource.create_group`). `AuthorizedOperation('create_resource', 'group')` passes sitewide. `build_group` (`web/server/routes/views/groups.py`) resolves role URIs with an unfiltered `Transaction.find_by_id`. `manager.create` commits the group with the admin role, then the handler adds a non-superuser creator as the only member (`update_group_users(group, [current_user.username])`). Next request, `_build_role_needs(group.roles)` yields `RoleNeed('admin')`.
2. **`PATCH /api2/group/<id>`** (`update_group`). The item resolves through `GroupResourceManager` (caller must be a member), then `edit_resource` on group, sitewide. Same `build_group`. The same body's `acls` go to `update_group_acls` unchecked, so a member with `edit_resource` on group can also hand the group `dashboard_admin` on any dashboard.
3. **`POST /api2/role`** (`create_role`). No route gate; the Potion mixin and `before_create` check `create_resource` on role. `build_role` resolves permissions, resource roles and query policies unfiltered, and `add_current_user_to_role` adds a non-superuser creator. The `update_permissions` gate exists only on `/api2/role/<id>/permissions` and `/permission`. `PATCH /api2/role/<id>` (`update_role`) has the same hole for any role the caller holds (`RoleResourceManager` scopes the item to held roles).

### The rule

A caller may attach to a group, or put into a role, only what it could grant directly. Refusals are `403` (werkzeug `Forbidden`, the status Potion's own permission mixin uses) and a `WARNING` audit line naming the caller and the refused grant.

- **Group roles** (`POST /api2/group`, `PATCH /api2/group/<id>`). Role URIs resolve through the same filter as `RoleResourceManager` (`roles_held_by`): a non-superuser can attach only roles it holds itself. The admin role is held only by superusers. A URI naming a role that exists but is not held is refused. A URI naming no role is skipped, as today.
- **Group ACLs** (same routes). Each resource role on a resource that the group does not already have needs `update_users` on that resource, the permission `POST /api2/resource/<id>/roles` already requires to share it. ACLs the group already has may be resent unchanged, so renaming a group never needs the grant again.
- **Role create** (`POST /api2/role`). Permissions or a dashboard or alert resource role need `update_permissions` on role, the gate on the `/permissions` routes. No seeded role holds it, so only admins pass. Query policies and data export remain allowed (the role is not visible to its creator unless the creator is added to it). The creator is added only when it already holds everything the role grants: each of the role's needs from `_build_role_needs` is in the caller's identity, and data export only if one of the caller's roles exports.
- **Role update** (`PATCH /api2/role/<id>`). Any change to permissions, resource roles, query policies or data export needs `update_permissions` on that role. Every holder of the role, including the caller, gains what is added. Label-only edits are unchanged.

Out of scope, recorded under Findings for the lead: the user-side grant paths, and the broken `/roles` sub-routes on users and groups.

### How to run the tests

`tests/web/privilege_escalation/` drives the real Flask app: `create_app_base`, Flask-User, Flask-Principal with the production signal handlers, header login, and `_register_potion_routes` (query resources are left out because they read Druid). The database is a throwaway `postgres:15.2-alpine` container on a free loopback port, built with `db.create_all()` and seeded with the harmony_demo roles the tests use. Set `HARMONY_TEST_DATABASE_URL` to use an existing empty database instead.

```bash
sed -E 's/^-e (git\+.*#egg=(.*))$/\2 @ \1/; s/#egg=.*$//' requirements.txt requirements-web.txt \
  | grep -v 'segment-analytics\|google-cloud-logging\|Flask-Admin\|graphene\|Flask-GraphQL' > /tmp/wp0h-reqs.txt
PYTHONPATH=$PWD uv run --no-project -p 3.8 --with-requirements /tmp/wp0h-reqs.txt \
  --with 'pytest<8' --with 'bcrypt<4.1' \
  python -m pytest tests/web/privilege_escalation -q -p no:cacheprovider -W ignore
```

`bcrypt<4.1` keeps passlib's password hashing working, as in `scripts/create_user.py`.

## Contract changes

None.

## Requests

## Log

- 2026-10-04 backend-6 unit 1: traced the three escalations through Potion, the managers and the need builder (notes above, under "How each escalation works"). Probing the same app also found the group ACL grant and the role PATCH variant. Check: each path reproduced in the unit 2 harness.
- 2026-10-04 backend-6 unit 2: `tests/web/privilege_escalation/` (18 tests: 9 escalation cases, 9 behaviours that must not change). Check: on the integration branch, 9 failed, each on `assert 200 == 403` or on the creator being auto-added; 9 passed.

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
