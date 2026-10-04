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

## INV-3 difference table

Only principals that already pass a route's existing gate reach the new checks. Those gates are unchanged:
- `create_resource` on group for `POST /api2/group`;
- `edit_resource` on group plus membership for `PATCH /api2/group/<id>`;
- `create_resource` on role for `POST /api2/role`;
- `edit_resource` on role plus holding the role for `PATCH /api2/role/<id>`.

So among the seeded roles only `group_admin`, `group_moderator`, `role_administrator` and `role_moderator` can see a difference. A custom role with the same permissions sees the same difference.

| Principal | Request | Before | After |
|---|---|---|---|
| `group_admin` | `POST /api2/group` naming a role it does not hold (the admin role included) | 200; the creator becomes the group's only member and holds the role | 403; nothing written; audit line |
| `group_admin`, `group_moderator` (member) | `PATCH /api2/group/<id>` adding a role it does not hold | 200; every member holds the role | 403; nothing written; audit line |
| `group_admin`, `group_moderator` | `POST` or `PATCH` a group with a new ACL (resource role on a resource) without `update_users` on that resource | 200; the group holds the resource role there | 403; nothing written; audit line |
| `role_administrator` | `POST /api2/role` with permissions or a dashboard or alert resource role | 200; the creator is added and holds them | 403; nothing written; audit line |
| `role_administrator` | `POST /api2/role` whose needs or data export the creator's account does not already hold (query policies, export) | 200; the creator is added | 200; the role is created, the creator is not added; info line |
| `role_administrator`, `role_moderator` (holder) | `PATCH /api2/role/<id>` changing permissions, resource roles, query policies or data export | 200; every holder gains the change | 403; nothing written; audit line |

Unchanged:
- Requests by superusers.
- Roles a caller holds, attached to a group.
- ACLs on resources the caller may share (`update_users` there, for example `dashboard_admin` of that dashboard).
- Roles and ACLs a group already has, resent in a PATCH.
- Role URIs naming no role (still skipped).
- Creating an empty role, or one whose needs the creator already holds (the creator is still added).
- Relabelling a held role.
- Every other route.
- Every Potion read and list filter. `RoleResourceManager` now calls the extracted `roles_held_by`, with the same filter.
- Gate failures before the new checks keep their status codes (401 from `AuthorizedOperation`, 403 from the Potion mixin). Only the new refusals are 403.

Seeded roles with no difference, because they cannot pass any of the four route gates: `dashboard_viewer`, `dashboard_editor`, `dashboard_admin`, `directory_reader`, `query_runner`, `user_admin`, `user_moderator`, `query_analyst`, `alert_*`, `_default_role`, `data_uploader_*`, `manager`, `data_upload_admin`, `data_catalog_viewer`, `field_setup_viewer`, `entity_matching_viewer`. The same holds for anonymous and public visitors, and for browser-session and render tokens.

The admin UI's group and role editors sit behind `view_admin_page`, which none of the four affected roles holds. Those roles reach these routes only through the API, so no screen changes for them.

## Findings for the lead

Outside this WP's scope. Each needs its own decision.

- **F1. User-side grants are unchecked.** `PATCH /api2/user/<id>` resolves role and group URIs and ACLs unfiltered (`build_user_updates`, `update_user_groups`, `update_user_acls`). It is gated only by `edit_user` on site plus `edit_resource` on user. No single seeded non-admin role holds both, but a principal with `manager` and `user_admin`, or a custom role combining them, can make any user, itself included, a site admin, or add users to any group. The same ceiling (`held_roles_from_uris`, `verify_acl_grants`) applies directly. Suggested follow-up WP, backend, Sec yes.
- **F2. The legacy `/roles` sub-routes on users and groups are broken and destructive.** They are `POST`, `PATCH` and `DELETE` on `/api2/user/<id>/roles` and `/api2/group/<id>/roles`.
  - **Adding a role fails.** `try_get_role_and_resource` looks up a `ResourceRole` by name, and `add_user_role`/`add_group_role` build `UserRoles`/`GroupRoles` with a `resource_id` column those tables do not have. Every add is a 500.
  - **`PATCH` deletes role rows.** It first runs `session.delete(role)` over the target's `Role` objects. Reproduced in this WP's harness: `PATCH /api2/user/<id>/roles` with `{}` by a `user_admin` deleted the `dashboard_admin` `Role` row itself (9 roles became 8). A `group_moderator` can do the same to its group's roles.
  - **The admin UI calls them.** `DirectoryService.updateUserRoles` and `updateGroupRoles` are used from `AdminApp/UsersTab/UserViewModal` and `DashboardSettingsModal/DashboardUsersTable`.
  - Recommend a backend plus frontend-platform WP: fix or remove the routes and their callers together.
- **F3. `update_roles` on group and user is seeded but never checked.** `group_admin` and `user_admin` hold it; nothing reads it. Recorded so a later port does not assume it gates anything.

## Contract changes

None.

## Requests

- [ ] qa: on `mig/WP-2b-authz-suite`, flip the three cases in `tests/authz/http/test_escalation.py` from pinned (200, `page:admin`) to refused. The cases are `test_group_admin_becomes_site_admin_by_creating_a_group_with_the_admin_role`, `test_group_moderator_becomes_site_admin_through_a_group_it_belongs_to` and `test_role_administrator_grants_itself_any_permission_through_a_new_role`. Each should expect 403, `/admin` still `page:unauthorizedPage`, and no group or role written. The rename and assertions are qa's call. Decision 0003 requires the flip in the same stack of commits as this fix. It blocks merge, not review.

## Log

- 2026-10-04 backend-6 unit 1: traced the three escalations through Potion, the managers and the need builder (notes above, under "How each escalation works"). Probing the same app also found the group ACL grant and the role PATCH variant. Check: each path reproduced in the unit 2 harness.
- 2026-10-04 backend-6 unit 2: `tests/web/privilege_escalation/` (18 tests: 9 escalation cases, 9 behaviours that must not change). Check: on the integration branch, 9 failed, each on `assert 200 == 403` or on the creator being auto-added; 9 passed.
- 2026-10-04 backend-6 unit 3: `web/server/security/grants.py`. The group routes resolve role URIs through `roles_held_by` (extracted from `RoleResourceManager`) and check new ACLs for `update_users`. The role routes pass the `update_permissions` gate, and `create_role` adds the creator only when it already holds the role's needs. `build_group` moved into `group_api_models.py` to avoid an import cycle. Check: `tests/web/privilege_escalation` 19 passed; ruff clean.
- 2026-10-04 backend-6 unit 4: INV-3 difference table, plus the WP-2b suite run against integration and this branch in scratch copies. Check: pure layer outcomes identical (2517 passed each). Live-stack layer: only the three pinned escalations differ (`assert 403 == 200`); 566 identical.

## Evidence

**This WP's tests** (`tests/web/privilege_escalation/`, command under "How to run the tests"):
- integration branch: `9 failed, 9 passed` (the 9 escalation cases fail on `assert 200 == 403` or on the auto-added creator);
- this branch: `19 passed`. That is the 18 plus `test_a_refused_grant_is_audited_with_the_caller`, which checks the WARNING line names the caller and the refused role.

**WP-2b pure layer** (`tests/authz/run.sh`, from `mig/WP-2b-authz-suite` at `d1e809a`), run in two scratch copies built with `git archive`: `mig/integration` plus the suite, and this branch plus the suite.
- Both: `2517 passed, 569 skipped` (the skips are the live-stack layer).
- Per-test outcomes (`-rA`, sorted, 2527 lines each) are byte-identical: `diff` printed nothing.

**WP-2b live-stack layer** (`tests/authz/run.sh -m authz_http`). Each scratch copy ran its own WP-2c stack: `AUTHZ_PROJECT=harmony-wp0h-authz-int` on port 58671 and `harmony-wp0h-authz-fix` on 58672, with the source mounted read-only. Both stacks were torn down afterwards.
- integration: `569 passed`.
- this branch: `3 failed, 566 passed`. The diff of per-test outcomes is exactly the three pinned escalations, each failing with `assert 403 == 200`:
  ```
  > FAILED tests/authz/http/test_escalation.py::test_group_admin_becomes_site_admin_by_creating_a_group_with_the_admin_role
  > FAILED tests/authz/http/test_escalation.py::test_group_moderator_becomes_site_admin_through_a_group_it_belongs_to
  > FAILED tests/authz/http/test_escalation.py::test_role_administrator_grants_itself_any_permission_through_a_new_role
  ```
  Every other live case is unchanged: seed drift, per-role page and API status codes, Potion list filtering, saved queries, and the admin self-delete guard. These three become passes once qa flips them (Requests).

**Static checks** on the touched files: `uvx ruff check web/server/security/grants.py tests/web/privilege_escalation` passes, and `uvx black -S` is clean for the new code. `black --check` still reports `group_api_models.py` and `permission_api_models.py`; that comes only from black-version differences in lines this WP does not touch (tuple-unpacking parentheses, a blank line after the module docstring), and the integration copies show the same.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
