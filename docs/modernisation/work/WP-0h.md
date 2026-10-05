---
wp: "0h"
title: "Close privilege escalations in group and role management"
status: review
owner_role: "backend"
instances:
  - name: "backend-6"
    files:
      - "web/server/api/group_api_models.py"
      - "web/server/api/permission_api_models.py"
      - "web/server/api/user_api_models.py"
      - "web/server/potion/managers.py"
      - "web/server/security/grants.py"
      - "web/server/routes/views/core.py"
      - "web/server/routes/views/groups.py"
      - "web/server/routes/views/permission.py"
      - "web/server/routes/views/users.py"
      - "tests/privilege_escalation/**"
      - "docs/modernisation/work/WP-0h.md"
branch: "mig/WP-0h-privilege-escalations"
requirements: [INV-3, QA-1, QA-4]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0h: Close privilege escalations in group and role management

Phase detail: [phase-0-security-and-subtraction.md, section 0h](../phase-0-security-and-subtraction.md). Added by [decision 0003](../decisions/0003-wp-0h-privilege-escalations.md); scope widened by [decision 0004](../decisions/0004-wp-0h-scope-and-wp-0i-render-routes.md). H5 moved to WP-0j by [decision 0005](../decisions/0005-wp-0j-account-takeover-via-rename-and-reset.md).

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Read the group and role Potion resources, their managers, and the permission plumbing (`pstack:how`). Check: notes in this file name the code paths behind each escalation.
2. Failing tests, one per escalation, through the real Flask app and Potion routes with constructed users. Check: the tests fail on the integration branch for the reason the escalation gives.
3. The fix for the three decision-0003 escalations and the group ACL grant. Check: the tests pass.
4. INV-3 difference table, plus the WP-2b suite run against the fix. Check: suite output recorded under Evidence.
5. `pstack:interrogate` on the fix (three reviewers), findings triaged below.
6. Decision 0004 and the interrogate findings, failing tests first for each:
   - N3, a `role_moderator` adding grants to a role it holds;
   - N4, query policies and data export a `role_administrator` does not hold;
   - N5, a group gaining a policy-carrying role the caller does not hold;
   - N6, `PATCH /api2/role/<id>/users`;
   - the `/users` self-add;
   - the `/roles` empty-map deletion of `Role` rows;
   - a narrowed admin JWT granting admin;
   - group ACLs without a resource.

   Check: the new tests fail on integration and pass here; the WP-2b suite is re-run.
7. `status: review`.
8. Rework after the c3a256f verdicts (qa, security, reviewer), failing tests first:
   - F1, the user-side grants on `PATCH /api2/user/<id>`;
   - one superuser definition (the identity) on every grant path, including the role and group Potion managers, which decide what a narrowed admin token reaches;
   - 403 bodies that name nothing the caller cannot list;
   - guards that survived the reviewer's mutation pass: pin each with a test, or remove it;
   - pylint E1101, types, the INV-3 rows for superuser-visible changes, and the doc fixes.

   Check: the tests pass here and the new ones fail on integration; a mutation pass over every guard; CI pylint and black on the changed files; WP-2b pure layer identical and live layer differing only in the pinned escalations.
9. Rework after security round 2 (`dc65f70`): `member_groups_from_uris` excludes admin-holding groups for a non-superuser identity, as `GroupResourceManager` does, failing test first. Check: the new narrowed-token case fails on `a615058` and passes here; WP suite, WP-2b pure layer.
10. Rework after the round-2 verdicts (reviewer, qa): merge `mig/integration` and pass WP-2f's CI gates on the merged tree (suite moved to `tests/privilege_escalation` so it runs in its own process; mypy and ruff findings), pin the two surviving guards, remove the dead `QueryNeed` filter, and correct the evidence. Check: `ci/lint_python.sh`, `uv run --locked mypy` and `ci/pytest_suites.sh` pass on the merged head; mutation of each new pin's guard fails its test; WP-2b pure layer identical.

### How each escalation works (unit 1)

The handlers turn caller-supplied ids into ORM objects without a filter, and every check is on the container (`create_resource`/`edit_resource` on `group` or `role`, all sitewide in the seed), never on what is granted.

1. **`POST /api2/group`** (`GroupResource.create_group`). `AuthorizedOperation('create_resource', 'group')` passes sitewide. `build_group` resolved role URIs with an unfiltered `Transaction.find_by_id`. `manager.create` commits the group with the admin role, then the handler adds a non-superuser creator as the only member. Next request, `_build_role_needs(group.roles)` yields `RoleNeed('admin')`.
2. **`PATCH /api2/group/<id>`** (`update_group`). The item resolves through `GroupResourceManager` (the caller must be a member, otherwise 404), then `edit_resource` on group, sitewide. Same `build_group`. The body's `acls` went to `update_group_acls` unchecked, so a member could hand the group `dashboard_admin` on any dashboard.
3. **`POST /api2/role`** (`create_role`). No route gate; the Potion mixin and `before_create` check `create_resource` on role. `build_role` resolves permissions, resource roles and query policies unfiltered (N4), and `add_current_user_to_role` adds a non-superuser creator. The `update_permissions` gate existed only on `/api2/role/<id>/permissions` and `/permission`. `PATCH /api2/role/<id>` (`update_role`) has the same hole for any role the caller holds (N3).

### The rule

A non-superuser may give a group, a user or a role only grants it already holds. Roles, groups and ACLs the target group or user already has may be sent again unchanged. Refusals are `403` (werkzeug `Forbidden`, the status Potion's own permission mixin uses) with a `WARNING` audit line naming the caller and the refused grant. All of it lives in `web/server/security/grants.py`.

- **Superuser** is one definition on every grant path: the identity holds `RoleNeed('admin')` (`current_user_is_superuser`, that is `SuperUserPermission`), not the account. A JWT narrowed on an admin account therefore grants like a non-superuser. The paths that use it:
  - `held_roles_from_uris`, `member_groups_from_uris` and `verify_role_grants` in `grants.py`. The first two never pass on the admin role or a group carrying it to a non-superuser identity;
  - `create_group`, which keeps the body's `users` only for a superuser (F4);
  - `create_role`, whose creator auto-add is skipped for a superuser;
  - `RoleResourceManager` and `GroupResourceManager`, which decide which role and group items a caller reaches, and so what `PATCH /api2/role/<id>/users`, `PATCH /api2/group/<id>` and the group `/users` routes can confer. Before this unit they asked the account, so a narrowed admin token reached the admin role and admin-holding groups and could confer admin through them (three cases of `test_a_narrowed_admin_token_cannot_grant_through_any_path` failed on `e1d065b`).

  `UserResourceManager` and `QueryPolicyResourceManager` still ask the account. They decide what a caller lists and which users it can edit, not what it grants; every grant on `PATCH /api2/user/<id>` goes through `grants.py`. See F4.
- **What a non-superuser holds** comes from its account: its roles, its groups, and the needs `get_permissions()` builds from them. The admin role is never held by a non-superuser identity, and a group carrying it is never reached. That case only arises for a narrowed token on an admin account. `test_policies_held_by_the_account_pass_under_a_narrowed_token` pins the account as the source.
- **Group roles** (`POST /api2/group`, `PATCH /api2/group/<id>`). Both routes call `held_roles_from_uris` next to `verify_acl_grants`.
  - A non-superuser may attach only roles it holds itself, directly or through a group.
  - This covers N5: a role carrying query policies is attached only by a caller holding that role.
  - Resending the group's roles needs no exemption: only members reach a group, and a member holds every role of its group.
  - A URI naming no role is skipped, as before. A URI that does not end in a numeric id is a 400.
- **403 bodies** say what kind of grant was refused and name nothing else: no role, group or policy names, ids or URIs. Listing them would reveal that an id the caller cannot list exists. The audit line carries them. The ACL refusal names the resource role and resource the caller sent; their existence is already visible as 404 against 403.
- **Group ACLs** (same routes).
  - Each resource role on a resource that the group does not already have needs `update_users` on that resource, the permission `POST /api2/resource/<id>/roles` requires to share it.
  - The type comes from the resolved resource, never from the request body.
  - An ACL without a resource is a 400: such a row breaks need building for every member.
  - The write stores exactly the `(resource_role, resource)` pairs that were authorised (`replace_group_acls`), instead of resolving the names a second time.
- **Role create and update** (`POST /api2/role`, `PATCH /api2/role/<id>`). Potion's own `create_resource`/`edit_resource` check now runs first, so a caller without it gets the usual 403 and no misleading audit line.
  - **Permissions and resource roles:** any change, on create or update, passes the `update_permissions` gate of the `/permissions` routes (phase 0h). No seeded role holds it, so in practice only admins pass.
  - **Query policies (N4):** every policy in the body must equal a policy the caller's account already holds. Equality, not `QueryNeed` containment: containment does not follow how policies combine into the Druid filter, so a broader held policy is not trusted to cover a narrower one.
  - **Data export (N4):** on needs a role of the caller's that exports.
  - **Resending a role's own policies and export** needs no exemption. A non-superuser reaches only roles it holds, so their policies and export are already its account's. The exemptions the reviewer found unreachable were removed.
  - **Creator auto-add:** the creator is added only when its account already holds every permission and resource role the role grants. Its policies and export already passed the checks above, so they are not compared again. This matters only for a non-admin holding `update_permissions`.
- **User grants (F1)**, `PATCH /api2/user/<id>`. The route is gated by `edit_user` on site. Potion's `edit_resource` on user now runs first, then every grant check, then the writes:
  - **roles:** `held_roles_from_uris`, with the user's current roles allowed to be resent;
  - **groups:** `member_groups_from_uris`. A non-superuser may add a user only to groups it belongs to, whose roles and ACLs it therefore holds, and never to a group carrying the admin role (that case only arises for a narrowed token on an admin account, as in `GroupResourceManager`). The user's current groups may be resent;
  - **ACLs:** `verify_acl_grants`, as for groups, with the user's current ACLs allowed to be resent. `replace_user_acls` writes exactly the authorised pairs.

  Removing roles, groups or ACLs is not a grant and is not checked. A refused request writes nothing, profile fields included.
- **N6, `PATCH /api2/role/<id>/users`.** Unchanged, by lead ruling under decision 0004 rule 1. The item resolves through `RoleResourceManager`, so the caller already holds the role it confers, and the route requires `edit_resource` on the role. The composition residual stays on the human acceptance list: a moderator can spread any role it holds. The pin keeps today's behaviour.
- **The `/users` self-add** (`POST`/`PATCH /api2/group/<id>/users`). It was not reproducible. `GroupResourceManager` gives a non-member a 404 on every group item route, and a member already holds every role of its group. Pinned by `test_group_moderator_reaches_only_groups_it_belongs_to`; no code change.
- **The `/roles` sub-routes** (`PATCH /api2/group/<id>/roles` and `/api2/user/<id>/roles`). With an empty map they ran `session.delete(role)` over the target's `Role` objects, deleting the rows themselves. They now unlink the target's roles. Adding through these routes still fails with a 500 (F2).
- **Unknown resource role names.** `try_get_role_and_resource` used to read `role.permissions[0]` before checking that the role exists, so an unknown name was a 500. It now compares `role.resource_type_id` and raises its own `NotFound` (404). That applies to every caller: `/api2/resource/<id>/roles`, group and user ACLs, and the `/roles` sub-routes (INV-3 row 14).

### How to run the tests

`tests/privilege_escalation/` drives the real Flask app: `create_app_base`, Flask-User, Flask-Principal with the production signal handlers, header login or the `accessKey` JWT cookie, and `_register_potion_routes` (query resources are left out because they read Druid). The database is a throwaway `postgres:15.2-alpine` container on a free loopback port, built with `db.create_all()` and seeded with the harmony_demo roles the tests use. Set `HARMONY_TEST_DATABASE_URL` to use an existing empty database instead.

```bash
uv run --locked pytest tests/privilege_escalation -q
```

It is its own directory under `tests/` because it builds a Flask app and registers the Potion resources for the whole process; `ci/pytest_suites.sh` runs each directory in its own process. Before the unit 10 merge the branch predated WP-2f and ran on a Python 3.8 environment built from `requirements*.txt`.

## INV-3 difference table

Only principals that already pass a route's existing gate reach the new checks. Those gates are unchanged:
- `create_resource` on group for `POST /api2/group`;
- `edit_resource` on group plus membership for `PATCH /api2/group/<id>` and its `/roles` and `/users` sub-routes;
- `create_resource` on role for `POST /api2/role`;
- `edit_resource` on role plus holding the role for `PATCH /api2/role/<id>` and `/users`;
- `edit_user` on site plus `edit_resource` on user for `PATCH /api2/user/<id>`;
- `edit_resource` on user for `PATCH /api2/user/<id>/roles`;
- `update_users` on the resource for `POST /api2/resource/<id>/roles`.

Who sees a difference:
- **Grant refusals** (rows 1-3, 7-13, 15-17) reach only non-superusers that pass those gates. Among seeded roles that means `group_admin`, `group_moderator`, `role_administrator`, `role_moderator` and `user_admin`, and the combination `manager` + `user_admin` (row 15-17; no single seeded role holds both `edit_user` on site and `edit_resource` on user). A custom role with the same permissions sees the same difference.
- **Input validation and data safety** (rows 4-6, 14, 18, 19) apply to every caller that reaches the route, superusers included.
- **Row 14** also reaches holders of `update_users` on a resource: `dashboard_admin`, alert admins, and dashboard owners through their owner ACL.

| # | Principal | Request | Before | After |
|---|---|---|---|---|
| 1 | `group_admin` | `POST /api2/group` naming a role it does not hold (the admin role included) | 200; the creator becomes the group's only member and holds the role | 403; nothing written; audit line |
| 2 | `group_admin`, `group_moderator` (member) | `PATCH /api2/group/<id>` adding a role it does not hold, including a role carrying query policies (N5) | 200; every member holds the role | 403; nothing written; audit line |
| 3 | `group_admin`, `group_moderator` | `POST` or `PATCH` a group with a new ACL (resource role on a resource) without `update_users` on that resource | 200; the group holds the resource role there | 403; nothing written; audit line |
| 4 | every caller, superusers included | a group ACL with an empty resource name | 200; a `GroupAcl` with no resource, which breaks every member's need building | 400; nothing written |
| 5 | every caller, superusers included | a group's role URI not ending in a numeric id | 500 | 400 |
| 6 | every caller, superusers included (`group_moderator` as member, `user_admin`, admin) | `PATCH /api2/group/<id>/roles` or `/api2/user/<id>/roles` with `{}` | 200; the target's `Role` rows are deleted for everyone | 200; the target's roles are unlinked, the `Role` rows stay |
| 7 | `role_administrator` | `POST /api2/role` with permissions or a dashboard or alert resource role | 200; the creator is added and holds them | 403; nothing written; audit line |
| 8 | `role_administrator` | `POST /api2/role` with query policies the account does not hold, or with data export when none of its roles exports (N4) | 200; the creator is added and reads that data | 403; nothing written; audit line |
| 9 | `role_administrator`, `role_moderator` (holder) | `PATCH /api2/role/<id>` adding, replacing or removing permissions or resource roles (N3) | 200; every holder sees the change | 403; nothing written; audit line |
| 10 | `role_administrator`, `role_moderator` (holder) | `PATCH /api2/role/<id>` adding query policies it does not hold, or turning on data export without exporting itself (N3, N4) | 200 | 403; nothing written; audit line |
| 11 | a non-admin holding `update_permissions` on role (no seeded role does) | `POST /api2/role` with permissions it does not hold | 200; the creator is added | 200; the creator is not added; info line |
| 12 | a JWT narrowed on an admin account. The render token is the one issued today; it is narrowed to `view_resource` on one dashboard and passes none of these gates | <ul><li>attach the admin role, or any role, to a group, add a user to an admin-holding group it belongs to through `PATCH /api2/user/<id>`, or grant through any path below</li><li>reach the admin role or an admin-holding group through the role and group item routes, including `PATCH /api2/role/<id>/users` and the group `/users` routes</li><li>`POST /api2/group` with `users`</li></ul> | <ul><li>200, granting admin</li><li>200</li><li>the body's users are set</li></ul> | <ul><li>403 or 404; nothing written</li><li>404</li><li>only the creator is added (F4)</li></ul> |
| 13 | a caller without `create_resource`/`edit_resource` on role | `POST`/`PATCH /api2/role` with an unknown resource role name; or with permissions | 500 (`build_role` ran first); 403 | 403 (Potion's check runs first); 403 with no grant audit line |
| 14 | every caller that reaches the route, superusers included | an unknown resource role name on `POST /api2/resource/<id>/roles`, a group or user ACL, or the `/roles` sub-routes | 500 (`role.permissions[0]` on a missing role) | 404 (`try_get_role_and_resource`'s `NotFound`) |
| 15 | `manager` + `user_admin` | `PATCH /api2/user/<id>`, on another user or itself, adding a role it does not hold (admin, a role carrying query policies, an exporting role) (F1) | 200; the user holds the role | 403; nothing written, profile fields included; audit line |
| 16 | `manager` + `user_admin` | `PATCH /api2/user/<id>` adding the user to a group the caller does not belong to (an admin-holding group, one sharing a dashboard) (F1) | 200; the user holds the group's roles and ACLs | 403; nothing written; audit line |
| 17 | `manager` + `user_admin` | `PATCH /api2/user/<id>` with a new ACL without `update_users` on its resource (for example `dashboard_admin` on itself) (F1) | 200 | 403; nothing written; audit line |
| 18 | every caller, superusers included | `PATCH /api2/user/<id>` with an ACL that has no resource | 500, after the profile fields and roles were committed | 400; nothing written |
| 19 | every caller, superusers included | `PATCH /api2/user/<id>` with a role or group URI not ending in a numeric id | 500 (a bad group URI only after the profile, roles and ACLs were committed) | 400; nothing written |

Unchanged:
- Grants by superusers. Rows 4-6, 14, 18 and 19 are the only differences a superuser sees.
- Roles a caller holds, attached to a group or given to a user. Groups the caller belongs to, given to a user. ACLs on resources the caller may share (`update_users` there).
- Roles, groups and ACLs a group or user already has, resent unchanged. A role's own policies and export, resent by a holder.
- Removing roles, groups or ACLs from a user or group, by any caller that passes the gates. That includes a non-superuser removing a user from an admin-holding group.
- Role URIs naming no role, and group URIs naming no group (still skipped).
- Creating an empty role, or one whose policies and export the creator already holds (the creator is still added).
- Adding a held query policy to a held role. Relabelling a held role.
- **N6:** unchanged by lead ruling under decision 0004 rule 1. `PATCH /api2/role/<id>/users` on a held role still confers it on other users (200); on a role the caller does not hold it is still 404.
- **The `/users` self-add:** non-members still get 404 on every group item route.
- `manager` alone on `PATCH /api2/user/<id>`: still 403, now from Potion's check before any grant is resolved, so there is no audit line.
- Users holding the admin role directly are still hidden (404) from non-superusers by `UserResourceManager`.
- Every other route, except row 14's 404 on `POST /api2/resource/<id>/roles`. Every Potion read and list filter for sessions that are not narrowed admin tokens. `RoleResourceManager` and `GroupResourceManager` differ only for a non-superuser identity on an admin account (row 12). The user and query-policy filters are untouched.
- Gate failures before the new checks keep their status codes: 401 from `AuthorizedOperation` on the group and user routes, 403 from the Potion mixin on the role routes. The new refusals are 403 as phase 0h asks. Moving the group routes' 401 to 403 would change today's outcomes for every principal lacking the container permission, so it is left for the FastAPI port (C-10).

Seeded roles with no difference, because they pass none of these route gates: `dashboard_viewer`, `dashboard_editor`, `directory_reader`, `query_runner`, `user_moderator`, `query_analyst`, `_default_role`, `data_uploader_*`, `manager` on its own, `data_upload_admin`, `data_catalog_viewer`, `field_setup_viewer`, `entity_matching_viewer`. `dashboard_admin` and the alert roles reach only row 14, and a `dashboard_editor` does too on dashboards it owns. The same holds for anonymous and public visitors and for browser sessions. Render tokens see row 12 only in principle, because they pass no gate.

The admin UI's group and role editors sit behind `view_admin_page`, which none of the affected roles holds. Those roles reach these routes only through the API. The admin UI itself runs as admin, so no screen changes.

## Interrogate (unit 5)

Three reviewers ran: opus (A), fable (B), and sonnet (C; it reported to the lead, who forwarded its findings with scope decisions). The sonnet run was first refused by the concurrent-subagent limit and relaunched once slots freed.

**Acted on:**
- **Narrowed admin JWT grants as admin** (A, B; B reproduced it). Fixed: superuser now comes from the identity in `grants.py`. Pinned by `test_an_admin_token_narrowed_to_groups_cannot_grant_admin`.
- **ACL without a resource** (A, C). A sitewide `GroupAcl` breaks every member's need building, and the authorisation type came from the body. Fixed: 400; the type comes from the resolved resource.
- **ACL check and write resolved names separately** (A; C noted it in passing). Fixed: the write stores the authorised pairs.
- **Grant checks ran before Potion's own checks** (A, B, C). Fixed for the role routes. The group routes already run `AuthorizedOperation` first.
- **`try_get_role_and_resource` dereferenced `role.permissions[0]` with no role** (C). Fixed: it compares `role.resource_type_id`.
- **`/roles` empty map deletes `Role` rows** (C, and F2 here). Fixed in both helpers.
- **Superuser audit line said "grants more than they hold"** (A, C). Fixed: superusers skip the auto-add decision.
- **The 403 body named roles the caller may not list** (B). Fixed: URIs in the body, names in the audit line.
- **Test gaps** (A, B, C): one field per case, alert resource role, the create-path ACL, unknown and malformed ids, a refused PATCH that also changes `users`, a JWT-cookie session, the resend exemption on a grant the caller really could not make (the old rename test passed through the role's sitewide `update_users`), a non-admin `update_permissions` holder, and an identical-resend no-op. All added.
- **Layering** (A, B, C). `grants.py` no longer imports from `potion.managers`; the `roles_held_by` extraction was reverted.
- **Nested comprehensions and two verifiers** (A, B, C). Merged into one `verify_role_grants`.
- **Shadowed variable** (A, B, C). Renamed.

**Not reproducible:**
- **`/users` self-add and refused resends for non-member moderators** (C 1, 2). A non-member gets 404 from `GroupResourceManager` on `GET`, `PATCH`, `POST /users` and `PATCH /users` of a group holding admin (`test_group_moderator_reaches_only_groups_it_belongs_to`). A member holds every role of its group, so resending them never fails.

**Pushed back:**
- **Use `QueryPermission` containment for held query needs** (C 6). Exact equality is kept, for two reasons:
  - Simple policies are ORed per dimension and ANDed across dimensions in `_construct_authorization_filter`, so `QueryNeed` containment (more dimensions is "superset") does not mean more data.
  - WP-2b Q7 records `QueryPermission` as having no callers.

  The cost is that a caller holding a broader policy cannot add a narrower one. An admin can.

**Noted:**
- `held_roles_from_uris` issues two queries (B). Kept for clarity.
- `roles` missing from a group body still fails as before (B).
- The group routes still commit in three steps, a pre-existing pattern (B).
- `conftest` transcribes the seed rather than running migrations (B). The WP-2b live layer, which uses the real migrations, is run below.

## Rework after the c3a256f verdicts (unit 8)

| Finding | From | Closure |
|---|---|---|
| F1, user-side grants on `PATCH /api2/user/<id>` | qa, security | Closed: roles, groups and ACLs checked (rule above, INV-3 rows 15-19). Failing first: 7 of the F1 tests fail on `0bb2525`, and 10 F1-path tests fail on integration. |
| pylint E1101, `Role.query` in `grants.py` | qa | Closed: session queries. CI's pylint 2.17.4 reports E1101 on `0bb2525`'s `grants.py:72` and no errors on any changed file now. `managers.py` joined the changed files, so its two pre-existing `.query` E1101s carry the same `no-member` disable `permission_api_models.py` uses. |
| N4 403 body names policy dimension and value; role URIs reveal ids | qa, security, reviewer | Closed: every 403 body names nothing (rule above). `test_role_administrator_cannot_create_a_role_reading_data_it_cannot_read` and `test_group_admin_cannot_create_a_group_holding_the_admin_role` assert no name, id or URI in the body. |
| INV-3 superuser-visible changes; row 9 removals | qa | Closed: rows 4-6, 14, 18 and 19 name every caller, superusers included. Row 9 says adding, replacing or removing. Pinned with admin cases (`test_a_malformed_role_uri_is_a_bad_request[admin]`, `test_a_group_acl_without_a_resource_is_a_bad_request[['admin']]`, `test_clearing_a_users_roles_keeps_the_roles[admin]`, `test_admin_sending_a_malformed_user_uri_gets_a_bad_request`, `test_admin_sending_a_user_acl_without_a_resource_gets_a_bad_request`). |
| Unknown resource role 500 to 404 (`core.py`) | reviewer | Code kept. INV-3 row 14, the "Every other route" line corrected, `test_an_unknown_resource_role_name_is_not_found`. |
| Guards surviving deletion | reviewer | See the mutation pass below: every remaining guard but one now fails a test when removed. The resend exemptions for a role's policies and export were removed, because a non-superuser reaches only roles it holds. So was the group-roles resend exemption the previous builder had left uncommitted, for the same reason. The identity half of the held-needs union was removed: what a caller holds comes from its account, pinned by `test_policies_held_by_the_account_pass_under_a_narrowed_token`. The Potion-first checks are pinned by `test_a_role_create_without_create_resource_is_refused_first` and `test_a_role_update_without_edit_resource_is_refused_first` (no audit line; 403 rather than 500 for an unknown resource role name, row 13). |
| Export clause and policy needs in `holds_everything_in` | reviewer | Removed: it compares only permissions and resource roles. |
| Grant check hidden in `build_group` | reviewer | Closed: both group routes call `held_roles_from_uris` beside `verify_acl_grants`. `build_group` takes the resolved roles. |
| Docstring of `held_roles_from_uris`; the reason for excluding admin | reviewer | Closed. |
| QA-1 and QA-4 in front matter | reviewer | Listed. Evidence below: QA-1 is the integration and `0bb2525` failing runs; QA-4 ("every page renders") is the WP-2b live layer's per-role page requests, unchanged. |
| Nits: `_is_superuser`, the account superuser check in `create_role`, types, repeated `if role else` | reviewer | `current_user_is_superuser` is used throughout `grants.py`, `create_group` and `create_role`. `RoleFields` (a TypedDict) types `build_role`'s output. Tighter `Iterable[...]`, `Mapping` and `set[Need]` types. A role's current permission ids and resource role ids are computed once. |
| Inconsistent superuser gating (lead, automated review of `e1d065b`) | lead | Closed: one definition on every grant path, including the role and group managers (rule above, INV-3 row 12). `test_a_narrowed_admin_token_cannot_grant_through_any_path` runs ten grant paths with a full admin session (200, granted) and with the same account's token narrowed to the container permissions (403 or 404, nothing written). Three of them granted admin on `e1d065b`; the tenth, added in unit 9, on `a615058`. |
| N6 | lead ruling | Unchanged under decision 0004 rule 1; composition residual on the human acceptance list. |
| H5, rename and reset-password takeover | security | Not fixed here, because F1 does not touch it: a rename keeps the user's groups through the resend rule. Moved to WP-0j by decision 0005. |

**Mutation pass** (`/tmp/wp0h_mut.py`; each mutation applied alone at `a23f729`, the suite run with `-x`, the file restored):

| Guard removed or weakened | Result |
|---|---|
| Potion check first: `create_role`, `update_role`, `update_user` | killed, each by its "refused first" test |
| held needs from the identity instead of the account | killed |
| `RoleResourceManager`/`GroupResourceManager` asking the account | killed (narrowed `role_users_route`, `group_users_route`) |
| their admin exclusions | killed |
| `held_roles_from_uris` asking the account; its admin exclusion | killed (narrowed-token tests) |
| resend of the user's existing roles, groups; resend of existing ACLs | killed (the two rename tests) |
| ACL without a resource is a 400 | killed |
| `create_group` asking the account | killed (`test_only_a_superuser_identity_sets_the_members_of_a_new_group[narrowed]`) |
| `holds_everything_in` always true | killed |
| `member_groups_from_uris`'s admin-group exclusion (unit 9) | killed (`test_a_narrowed_admin_token_cannot_grant_through_any_path[narrowed-user_patch_admin_group]`, run before the fix) |
| `create_role`'s superuser early return asking the account | survives. The outcome cannot differ: a narrowed admin can only create a role without permissions, which it holds, and `add_current_user_to_role` skips admin accounts. It is kept so `grants.py` and the routes share one definition. |

## Rework after security round 2 (unit 9)

| Finding | From | Closure |
|---|---|---|
| `member_groups_from_uris` allowed every group of the caller's account, so an admin account in an admin-holding group, on a token narrowed to `edit_user` and `edit_resource`, could add a user to that group through `PATCH /api2/user/<id>` (200, no audit line) | security, Medium | Closed in `e58c67a`: a non-superuser identity is refused groups carrying the admin role, the same exclusion as `GroupResourceManager` and `held_roles_from_uris`. Failing first: `test_a_narrowed_admin_token_cannot_grant_through_any_path[narrowed-user_patch_admin_group]` got `assert 200 in (403, 404)` on `a615058`; its full-session half (200, granted) passes on both. F4 and INV-3 row 12 now hold as written: every grant path, user groups included, refuses a narrowed admin token. Only `PATCH /api2/user/<id>` writes a user's groups (`update_user_groups`), so no other route needed the change. |
| H5 | security | Moved to WP-0j (decision 0005). Requests updated. |

## Rework after the round-2 verdicts (unit 10)

| Finding | From | Closure |
|---|---|---|
| `member_groups_from_uris` keeps admin-holding groups for narrowed tokens | reviewer, qa (same as security's) | Closed in unit 9. QA's probe (`/tmp/qa0h-r2-evidence/test_qa_probe.py`, copied in temporarily) passes on `98e77fc`: 6 passed, including an account that is admin only through the group. |
| CI gates red on the merge with integration | reviewer (high), qa (high) | Merged `mig/integration` (`df01179` at `56deb80`, `044a457` at `1697a7a`). The suite moved to `tests/privilege_escalation`, so `tests/web/test_graphql_endpoint_removed.py` no longer shares its process. mypy: `users.py` `user.roles.remove` and `grants.py` `role.permissions` carry `# type: ignore[attr-defined]` (sqlmypy types an untyped `relationship` as one object; the models are core's). ruff: the unused `create_dashboard_permission_updates` import removed, `APIToken.is_revoked.is_(False)`, three files formatted. Evidence now cites `ci/lint_python.sh`, mypy and `ci/pytest_suites.sh`. |
| `member_groups_from_uris`'s superuser early return survives deletion | reviewer (medium) | Pinned by `test_admin_adds_a_user_to_a_group_it_is_not_in` (200, membership written); deleting the return fails it. |
| `QueryNeed` filter in `holds_everything_in` is dead | reviewer (low) | Removed with the import. The role's query needs already passed `verify_role_grants` against the same account needs. |
| `try_get_role_and_resource`'s `resource_type_id` comparison unpinned | reviewer (low) | `test_an_unknown_resource_role_name_is_not_found` now also sends `alert_admin` on a dashboard through a user and a group ACL: 404, no ACL written on either. Removing the comparison fails both. |
| Live layer pins 10 escalations at `f2e04ac`, not 6 | qa (low) | Evidence and the qa request list all ten. |
| Static-check evidence cites pylint and black | qa (low) | Replaced for this round by ruff and mypy through the CI scripts; the unit 6 and unit 8 static checks are marked as pre-WP-2f. |
| Unit 8 log date | reviewer (nit) | 2026-10-05. |

## Findings for the lead

Outside this WP's scope. Each needs its own decision.

- **F1.** Closed in this WP (unit 8).
- **F2. The legacy `/roles` sub-routes still cannot add.** `POST`/`PATCH` on `/api2/user/<id>/roles` and `/api2/group/<id>/roles` look up a `ResourceRole` by name, then build `UserRoles`/`GroupRoles` with a `resource_id` column those tables do not have. Every add is a 500. The `PATCH` form also commits the unlink of the target's roles before that 500 (security, low, pre-existing). This WP fixed only their deletion of `Role` rows (table row 6). `web/python_client/directory_service/service.py` calls both `PATCH` routes whenever a user's or group's `roles` is set. The JS `DirectoryService.updateUserRoles`/`updateGroupRoles` have no component callers. Recommend fixing or removing the routes together with the python client.
- **F3. `update_roles` on group and user is seeded but never checked.** `group_admin` and `user_admin` hold it; nothing reads it.
- **F4. Narrowed tokens.** Every grant path now decides "superuser" from the identity: `grants.py`, `create_group`'s choice of members, `create_role`'s auto-add, and the role and group managers' reach. `test_a_narrowed_admin_token_cannot_grant_through_any_path` and `test_only_a_superuser_identity_sets_the_members_of_a_new_group` pin it. The residuals are reads and edits, not grants:
  - `UserResourceManager` and `QueryPolicyResourceManager` still decide from the account. A narrowed admin token lists every user and policy, and can edit users holding admin directly, but every grant in that edit is checked against the identity: roles, groups (admin-holding groups excluded since unit 9) and ACLs.
  - What a non-superuser holds comes from the account, so a narrowed non-admin token can grant whatever its account holds, given the container permission.
  - The one narrowed token issued today is the render token. It carries `view_resource` on one dashboard and passes no grant gate. WP-0i owns it.
  - Moving the user and policy filters to the identity would hide admins, the render bot included, from render tokens. That belongs with WP-0i.

## Human acceptance

Security asks the human to accept:
- INV-3 rows 1-19.
- **The N6 composition residual.** By lead ruling under decision 0004 rule 1, a holder of `edit_resource` on role can confer every role it holds through `PATCH /api2/role/<id>/users`, `role_moderator` included. Combined with the group and user paths, a moderator can spread any role it holds to any user, though never beyond what it holds.
- **The narrowed-token residuals in F4.**
- **F1's new rows (15-19).** A non-superuser user editor can still remove any role, group or ACL from a user it reaches, including demoting a user who is an admin through a group. Removal is not a grant.

## Contract changes

None.

## Requests

- [ ] qa: on `mig/WP-2b-authz-suite`, flip the pinned escalation cases from today's outcome to refused, in the same stack as this fix (decisions 0003, 0004). It blocks merge, not review. The expected outcomes on this branch:
  - `test_group_admin_becomes_site_admin_by_creating_a_group_with_the_admin_role`: 403, `/admin` stays `page:unauthorizedPage`, no group written.
  - `test_group_moderator_becomes_site_admin_through_a_group_it_belongs_to`: 403, group roles unchanged.
  - `test_role_administrator_grants_itself_any_permission_through_a_new_role`: 403, no role written.
  - **N3**, `role_moderator` PATCHes a held role adding a permission: 403.
  - **N4**, `role_administrator` creates a role with `/api2/query_policy/1` or `/2`, or with `dataExport: true`: 403 unless its account holds those policies or exports.
  - **N5**, `group_moderator` attaches `_default_role` to its group: 403 unless it holds `_default_role`.
  - **N6**, `PATCH /api2/role/<id>/users`: unchanged, 200 on a held role and 404 otherwise. See the INV-3 table.
  - **`/users` self-add**: unchanged, 404 for a non-member.
  - **N4 on update**, `test_role_editor_attaches_all_values_policies_and_data_export_to_a_held_role[role_administrator]` and `[role_moderator]`: 403.
  - **Empty role maps**, `test_group_moderator_empty_role_map_deletes_the_group_roles_for_everyone` and `test_user_admin_empty_role_map_deletes_the_user_roles_for_everyone`: 200, the target's roles unlinked and the `Role` rows kept.
  - At `f2e04ac` the live layer pins ten of these: H1-H3, N3, N4 (create, and update by `role_administrator` and `role_moderator`), N5 and both empty role maps. QA's run on a trial merge: all ten fail on this branch and nothing else changes (Evidence).
  - **F1**, if the suite pins it: `manager` + `user_admin` on `PATCH /api2/user/<id>` adding admin, an unheld group, or a `dashboard_admin` ACL gets 403. `test_user_admin_cannot_change_roles_through_the_user_form` (`user_admin` alone) is unchanged.
- [x] lead: routed by decision 0005 to WP-0j (backend, Sec yes); not this WP's scope. Original request: security's H5 (WP-2b) is not fixed here. `manager` + `user_admin` can rename a user who is an admin through a group, keeping the group by the resend rule, then pass the reset-password check, so the reset goes to an address the caller chose. That is a possible account takeover, unconfirmed. F1 does not reach it, because it is a profile edit, not a grant. Candidate rules are refusing a non-superuser's edit to the username of a user holding grants the caller does not hold, or checking the reset target's roles. Needs its own decision; suggested owner backend, Sec yes.

## Log

- 2026-10-04 backend-6 unit 1: traced the three escalations through Potion, the managers and the need builder (notes above). Probing the same app also found the group ACL grant and the role PATCH variant. Check: each path reproduced in the unit 2 harness.
- 2026-10-04 backend-6 unit 2: `tests/web/privilege_escalation/` (18 tests: 9 escalation cases, 9 behaviours that must not change). Check: on integration 9 failed, each on `assert 200 == 403` or on the creator being auto-added; 9 passed.
- 2026-10-04 backend-6 unit 3: `web/server/security/grants.py` and the route changes. Check: 19 passed; ruff clean.
- 2026-10-04 backend-6 unit 4: INV-3 table; WP-2b suite at `d1e809a` against integration and this branch. Check: pure layer identical (2517 passed each); live layer differs only in the three pinned escalations.
- 2026-10-05 backend-6 unit 5: `pstack:interrogate` with opus, fable and sonnet; triage above.
- 2026-10-05 backend-6 unit 6: decision 0004 scope and the interrogate fixes. Check: 36 passed here; the same file against integration `3780c8c` gives `22 failed, 14 passed`.
- 2026-10-05 backend-7 unit 8 (resumed from backend-6's uncommitted rework after the host reboot): F1, one superuser definition on every grant path including the role and group managers, generic 403 bodies, the reviewer's guard and type fixes, INV-3 rows 4-6, 9, 12-19. Commits `e1d065b`, `a23f729`. Check: 81 passed here; the same file against integration `3780c8c` gives `49 failed, 32 passed`. Mutation pass killed every guard but one (recorded). CI pylint has no errors and black 22.6.0 is clean on the changed files. WP-2b pure layer identical. Live layer: integration 575 passed; this branch 569 passed, and the 6 failures are exactly the pinned escalations.
- 2026-10-05 backend-8 unit 9: `member_groups_from_uris` admin-group exclusion after security round 2, commit `e58c67a`; H5 pointed at WP-0j (decision 0005). Check: the new narrowed-token case failed first (200); 83 passed here; the file on integration `3780c8c` gives `50 failed, 33 passed`; CI pylint no errors and black 22.6.0 clean on the WP's 11 changed Python files; WP-2b pure layer (`09a7581`) `4675 passed, 580 skipped` on both, outcomes byte-identical.
- 2026-10-05 backend-8 unit 10: merged `mig/integration` (`1697a7a`), suite moved to `tests/privilege_escalation`, mypy and ruff fixes, two guards pinned, dead `QueryNeed` filter removed, evidence corrected; commits `df01179`, `98e77fc`, `044a457`. Check: `ci/lint_python.sh mig/integration` and `uv run --locked mypy` pass; `ci/pytest_suites.sh` all 9 suites pass (86 here); the file on integration `1697a7a` gives `50 failed, 36 passed`; the new pins kill their guards; WP-2b pure layer byte-identical.

## Evidence

**Unit 10 (merged head `044a457`; code at `98e77fc`):**
- `ci/lint_python.sh mig/integration` (the 11 Python files this WP changes): `All checks passed!`, `11 files already formatted`.
- `uv run --locked mypy`: `Success: no issues found in 518 source files`.
- `ci/pytest_suites.sh`: `all 9 suites passed`. `tests/core` 25, `tests/druid` 1, `tests/druid_setup` 79, `tests/golden` 269, `tests/graphql` 22, `tests/pipeline` 129 (1 skipped), `tests/privilege_escalation` 86, `tests/toolchain` 9, `tests/web` 95 (including `test_graphql_endpoint_removed.py`).
- QA-1: the file on integration `1697a7a` gives `50 failed, 36 passed`. The three new pins (`test_admin_adds_a_user_to_a_group_it_is_not_in`, the two `alert_admin` cases) hold behaviour that is unchanged, so they pass on both.
- Mutation, each applied alone and restored: deleting `member_groups_from_uris`'s superuser return fails `test_admin_adds_a_user_to_a_group_it_is_not_in`; disabling the `resource_type_id` comparison fails `test_an_unknown_resource_role_name_is_not_found[user-alert_admin]` and `[group-alert_admin]`; deleting the admin-group exclusion fails `[narrowed-user_patch_admin_group]`.
- QA's probe (`test_qa_probe.py`): 6 passed.
- WP-2b pure layer, suite at `09a7581`, scratch copies of integration `1697a7a` and `044a457`: `4675 passed, 580 skipped` on both; sorted outcomes (4687 lines each) identical.
- WP-2b live layer: not re-run by this unit. QA's round-2 run on a trial merge of `dc65f70` with `8638861` gave `580 passed` on base and `570 passed` on the merge, the 10 failures being exactly the pinned escalations listed under Requests. Since then, the code changes are the admin-group exclusion (narrowed admin tokens only), the `is_(False)` rewrite of an equivalent filter, formatting and type ignores.

**Unit 9 (`e58c67a`):**
- WP tests: `83 passed` (81 plus both halves of the `user_patch_admin_group` path). Before the fix: `1 failed, 19 passed` under `-k narrowed_admin_token`, the failure `assert 200 in (403, 404)` on the narrowed half.
- QA-1: the file on integration `3780c8c` gives `50 failed, 33 passed`.
- Static checks: superseded by unit 10's CI gates on the merged tree.
- WP-2b pure layer, suite from `mig/WP-2b-authz-suite` at `09a7581`, scratch copies of `3780c8c` and `e58c67a` built with `git archive`: `4675 passed, 580 skipped` on both; sorted `-rA` outcomes (4687 lines each) byte-identical.
- Live layer: see unit 10.

**This WP's tests** (then `tests/web/privilege_escalation/`, command under "How to run the tests"):
- this branch at `a23f729`: `81 passed`.
- **QA-1.** Integration `3780c8c` with this branch's test file copied in gives `49 failed, 32 passed`. Each failing case is an escalation, a narrowed-token grant, a destructive path or a validation change this WP makes (INV-3 rows). The 32 passes are the behaviours that must not change: N6, the `/users` 404s, the resend cases, removals, and the full-admin-session halves of the narrowed-token tests.
  - At unit 6 (`c3a256f`) the file gave `22 failed, 14 passed` on integration.
  - The F1 and N4-body tests also failed on `0bb2525`, the head before this unit: `8 failed, 38 passed`, the 8 being the 7 F1 grant tests and the N4 body.
  - The three narrowed-token manager cases failed on `e1d065b`.
- `test_a_refused_grant_is_audited_with_the_caller` checks that the WARNING line names the caller and the refused role.

**WP-2b suite at `ca58b7d`** (unit 8), run in scratch copies built with `git archive`: integration `3780c8c` plus the suite, and `a23f729` plus the suite. Each copy also got the WP-2c stack from `mig/WP-2c-api-contract-recordings` (`fa72fe0`).
- **Pure layer:** `4672 passed, 575 skipped` on both. Per-test outcomes (`-rA`, sorted, 4682 lines each) are byte-identical.
- **Live-stack layer** (`tests/authz/run.sh -m authz_http`; `harmony-wp0h-authz-int` on 58671 and `harmony-wp0h-authz-fix` on 58672, source mounted read-only, both torn down):
  - integration: `575 passed`.
  - this branch: `6 failed, 569 passed`. The outcome diff is exactly the six pinned escalations, each `assert 403 == 200`: `test_group_admin_becomes_site_admin_by_creating_a_group_with_the_admin_role`, `test_group_moderator_becomes_site_admin_through_a_group_it_belongs_to`, `test_group_moderator_gains_all_values_policies_by_attaching_a_role`, `test_role_administrator_attaches_all_values_policies_and_data_export`, `test_role_administrator_grants_itself_any_permission_through_a_new_role`, `test_role_moderator_adds_a_permission_to_a_role_it_holds`.
  - **QA-4 ("every page renders").** `tests/authz/http/test_requests.py` requests every page and API row in `requests.yaml` for every seeded role and an anonymous visitor: 375 passed on both stacks with identical outcomes. List filtering (162), saved queries (26) and seed drift (2) are unchanged too. The live harness creates every principal through admin `PATCH /api2/user/<id>`, the route F1 changed.

**Static checks (unit 8, before WP-2f was merged in; superseded by unit 10):**
- CI's pylint 2.17.4 over every changed Python file reports no errors. It reports E1101 at `0bb2525`'s `grants.py:72`. The remaining warnings are pre-existing.
- black 22.6.0 `-S -t py39 --check` (CI's) is clean on all changed files.
- `uvx ruff check web/server/security/grants.py tests/web/privilege_escalation` passes.

**WP-2b suite at `e835c77` (unit 6, at `c3a256f`; superseded by the unit 8 run above)**, run in scratch copies built with `git archive`: integration `3780c8c` plus the suite, and this branch's HEAD plus the suite.
- Pure layer: `4258 passed` on both. Per-test outcomes (`-rA`, sorted, 4268 lines each) are byte-identical.
- Live-stack layer (`tests/authz/run.sh -m authz_http`): each copy ran its own WP-2c stack (`AUTHZ_PROJECT=harmony-wp0h-authz-int` on port 58671 and `harmony-wp0h-authz-fix` on 58672, source mounted read-only; both torn down afterwards).
  - integration: `569 passed`.
  - this branch: `3 failed, 566 passed`. The outcome diff is exactly the three pinned decision-0003 escalations, each `assert 403 == 200`:
    ```
    > FAILED tests/authz/http/test_escalation.py::test_group_admin_becomes_site_admin_by_creating_a_group_with_the_admin_role
    > FAILED tests/authz/http/test_escalation.py::test_group_moderator_becomes_site_admin_through_a_group_it_belongs_to
    > FAILED tests/authz/http/test_escalation.py::test_role_administrator_grants_itself_any_permission_through_a_new_role
    ```
  - Every other live case is unchanged: seed drift, per-role page and API status codes, Potion list filtering, saved queries, and the admin self-delete guard.
  - The N3 to N6 pins were not yet on the suite branch at `e835c77`. qa flips or adds them on this branch (Requests).

**Static checks (unit 6, superseded by unit 10):** `uvx ruff check web/server/security/grants.py tests/web/privilege_escalation` passes; `uvx black -S --check` is clean on both. Edits elsewhere keep each file's existing formatting, and black-version differences in untouched lines are left alone.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | changes-requested | 2026-10-05 | 2026-10-05 qa-0h round 2 at dc65f70: behaviour claims reproduce on branch, base and a trial merge with 8638861 (81 WP tests pass on the merge, 49 fail on base behaviourally; WP-2b pure layer byte-identical; live layer 580 on base and 570 on the merge with exactly the 10 pinned escalations failing, not 6; F1 probes rows 15-17 are 200 on base and 403 with nothing written and one audit line on the merge; INV-3 rows 1-10, 13, 14, 18, 19 match; 403 bodies name nothing except the documented ACL case). Fix: (medium) member_groups_from_uris keeps admin-holding groups for narrowed tokens (probe test at /tmp/qa0h-r2-evidence/test_qa_probe.py); (high) CI gates red on the merge: mypy users.py:266 Role has no remove and grants.py:177 Permission has no __iter__; ruff F401 permission_api_models.py:51, E712 users.py:420, three files to format; tests/web fails test_graphql_endpoint_removed because the privilege_escalation harness registers Potion resources first in the same process (move the suite to its own top-level directory); (low) evidence cites ca58b7d with 6 pinned failures, f2e04ac pins 10 (add the two N4-update and two empty-role-map cases) and static-check evidence must cite ruff and mypy, not pylint and black. |
| reviewer | changes-requested | 2026-10-05 rev-0h round 3 at b094556: five of six round-2 findings closed and each pinned (admin-group exclusion, superuser early return, resource-type comparison, dead QueryNeed filter, log date); the two type ignores are acceptable (removing them reproduces exactly the stated mypy errors; root fix is phase 3e replacing sqlalchemy-stubs, which should enable warn_unused_ignores); task_gate lists only status and verdicts; evidence names all ten pinned cases; is_(False) equivalent. Fix (high, INV-1): commit 98e77fc ran ruff format under py39 and turned the chained with in RoleResource.update_users (permission_api_models.py:566-569) into a parenthesised with containing an as-clause, which is 3.9-only syntax; the web image runs CPython 3.8.20 and create_app imports RoleResource, so the web server cannot start (verified: the branch has 1 syntax error on 3.8, integration 0; the WP suite on the 3.8 env stops at setup; with the lines restored 86 pass); integration now targets py38 (1c8578e) and the lint gate on a trial merge fails with invalid-syntax at 566:14; merge integration, restore the integration form of that with-statement, re-run the three gates; (low) evidence must record the gates on the current integration merge and one CPython 3.8 run (WP suite on the 3.8 web env or the WP-2b live layer); (low) the backend memory note saying 3.8 no longer matters after WP-2f is wrong until WP-3b. |
| security | changes-requested | 2026-10-05 | 2026-10-05 sec-0h round 2 at dc65f70 (live, branch vs base, WP harness on a throwaway Postgres): WP suite 81 passed on head and 51 failed on base; H1-H3, N3-N5 and every F1 variant (self or other admin, admin-holding group, shared-dashboard group, dashboard_admin ACL, query and export roles, nested and malformed URIs, label collisions) refused with 403, nothing written and an audit line; 403 bodies carry only the description; audit lines carry identity and the refused grant, no secrets; semgrep 260 rules on 9 files: one pre-existing url_for external at permission_api_models.py:272 outside the diff (WP-5d); ownership clean. Fix (Medium, blocks): grants.py:120-122 member_groups_from_uris allows every group in current_user.groups with no admin-holding-group exclusion, so an admin account that is a member of an admin-holding group, on a token narrowed to edit_user and edit_resource, adds a target to that group via PATCH /api2/user/id and makes them admin (200 on base and head, no audit line; the role control is 403); mirror the GroupResourceManager exclusion and pin a narrowed-token user-PATCH case where the admin account is a member of the admin-holding group; production reachability nil today (only the render token is narrowed). H5 confirmed live on base and head (Medium, pre-existing, out of 0h scope): manager plus user_admin renames an admin-through-group user to an attacker address (200, groups kept by the resend rule) then POST reset_password mails the new address, takeover of the admin account; belongs in a new phase-0 WP (backend, Sec yes) with the INV-3 row: non-superuser username change or password reset of a user whose grants exceed the caller's goes from 200 to 403 with an audit line. |
