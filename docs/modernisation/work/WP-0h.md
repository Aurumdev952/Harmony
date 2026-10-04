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
      - "web/server/security/grants.py"
      - "web/server/routes/views/core.py"
      - "web/server/routes/views/groups.py"
      - "web/server/routes/views/users.py"
      - "tests/web/privilege_escalation/**"
      - "docs/modernisation/work/WP-0h.md"
branch: "mig/WP-0h-privilege-escalations"
requirements: [INV-3]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0h: Close privilege escalations in group and role management

Phase detail: [phase-0-security-and-subtraction.md, section 0h](../phase-0-security-and-subtraction.md). Added by [decision 0003](../decisions/0003-wp-0h-privilege-escalations.md); scope widened by [decision 0004](../decisions/0004-wp-0h-scope-and-wp-0i-render-routes.md).

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

### How each escalation works (unit 1)

The handlers turn caller-supplied ids into ORM objects without a filter, and every check is on the container (`create_resource`/`edit_resource` on `group` or `role`, all sitewide in the seed), never on what is granted.

1. **`POST /api2/group`** (`GroupResource.create_group`). `AuthorizedOperation('create_resource', 'group')` passes sitewide. `build_group` resolved role URIs with an unfiltered `Transaction.find_by_id`. `manager.create` commits the group with the admin role, then the handler adds a non-superuser creator as the only member. Next request, `_build_role_needs(group.roles)` yields `RoleNeed('admin')`.
2. **`PATCH /api2/group/<id>`** (`update_group`). The item resolves through `GroupResourceManager` (the caller must be a member, otherwise 404), then `edit_resource` on group, sitewide. Same `build_group`. The body's `acls` went to `update_group_acls` unchecked, so a member could hand the group `dashboard_admin` on any dashboard.
3. **`POST /api2/role`** (`create_role`). No route gate; the Potion mixin and `before_create` check `create_resource` on role. `build_role` resolves permissions, resource roles and query policies unfiltered (N4), and `add_current_user_to_role` adds a non-superuser creator. The `update_permissions` gate existed only on `/api2/role/<id>/permissions` and `/permission`. `PATCH /api2/role/<id>` (`update_role`) has the same hole for any role the caller holds (N3).

### The rule

A non-superuser may attach to a group, or put into a role, only grants it already holds. Grants a group or role already has may be sent again unchanged. Refusals are `403` (werkzeug `Forbidden`, the status Potion's own permission mixin uses) with a `WARNING` audit line naming the caller and the refused grant. All of it lives in `web/server/security/grants.py`.

- **Superuser** means the identity holds `RoleNeed('admin')` (`SuperUserPermission`), not that the account holds the admin role. A JWT narrowed to some needs on an admin account therefore grants like a non-superuser.
- **Group roles** (`POST /api2/group`, `PATCH /api2/group/<id>`).
  - A non-superuser may attach only roles it holds itself, directly or through a group; this is the same filter `RoleResourceManager` applies to reads.
  - This covers N5: a role carrying query policies is attached only by a caller holding that role.
  - A URI naming no role is skipped, as before. A URI that does not end in a numeric id is a 400.
  - The 403 body lists role URIs. Role names go only to the audit line, because `RoleResourceManager` hides unheld roles from the caller.
- **Group ACLs** (same routes).
  - Each resource role on a resource that the group does not already have needs `update_users` on that resource, the permission `POST /api2/resource/<id>/roles` requires to share it.
  - The type comes from the resolved resource, never from the request body.
  - An ACL without a resource is a 400: such a row breaks need building for every member.
  - The write stores exactly the `(resource_role, resource)` pairs that were authorised (`replace_group_acls`), instead of resolving the names a second time.
- **Role create and update** (`POST /api2/role`, `PATCH /api2/role/<id>`). Potion's own `create_resource`/`edit_resource` check now runs first, so a caller without it gets the usual 403 and no misleading audit line.
  - **Permissions and resource roles:** any change, on create or update, passes the `update_permissions` gate of the `/permissions` routes (phase 0h). No seeded role holds it, so in practice only admins pass.
  - **Query policies (N4):** added policies must equal a policy the caller's account already holds. Equality, not `QueryNeed` containment: containment does not follow how policies combine into the Druid filter, so a broader held policy is not trusted to cover a narrower one.
  - **Data export (N4):** turning it on needs a role of the caller's that exports.
  - **Creator auto-add:** the creator is added only when its account already holds every need the role grants. This matters only for a non-admin holding `update_permissions`.
- **N6, `PATCH /api2/role/<id>/users`.** The item resolves through `RoleResourceManager`, so the caller already holds the role it confers. That is within the rule, so N6 is pinned by a test, not changed (see the INV-3 table).
- **The `/users` self-add** (`POST`/`PATCH /api2/group/<id>/users`). It was not reproducible. `GroupResourceManager` gives a non-member a 404 on every group item route, and a member already holds every role of its group. Pinned by `test_group_moderator_reaches_only_groups_it_belongs_to`; no code change.
- **The `/roles` sub-routes** (`PATCH /api2/group/<id>/roles` and `/api2/user/<id>/roles`). With an empty map they ran `session.delete(role)` over the target's `Role` objects, deleting the rows themselves. They now unlink the target's roles. Adding through these routes still fails with a 500 (F2).

### How to run the tests

`tests/web/privilege_escalation/` drives the real Flask app: `create_app_base`, Flask-User, Flask-Principal with the production signal handlers, header login or the `accessKey` JWT cookie, and `_register_potion_routes` (query resources are left out because they read Druid). The database is a throwaway `postgres:15.2-alpine` container on a free loopback port, built with `db.create_all()` and seeded with the harmony_demo roles the tests use. Set `HARMONY_TEST_DATABASE_URL` to use an existing empty database instead.

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
- `edit_resource` on group plus membership for `PATCH /api2/group/<id>` and its `/roles` and `/users` sub-routes;
- `create_resource` on role for `POST /api2/role`;
- `edit_resource` on role plus holding the role for `PATCH /api2/role/<id>` and `/users`;
- `edit_resource` on user for `PATCH /api2/user/<id>/roles`.

So among the seeded roles only `group_admin`, `group_moderator`, `role_administrator`, `role_moderator` and `user_admin` can see a difference. A custom role with the same permissions sees the same difference.

| # | Principal | Request | Before | After |
|---|---|---|---|---|
| 1 | `group_admin` | `POST /api2/group` naming a role it does not hold (the admin role included) | 200; the creator becomes the group's only member and holds the role | 403; nothing written; audit line |
| 2 | `group_admin`, `group_moderator` (member) | `PATCH /api2/group/<id>` adding a role it does not hold, including a role carrying query policies (N5) | 200; every member holds the role | 403; nothing written; audit line |
| 3 | `group_admin`, `group_moderator` | `POST` or `PATCH` a group with a new ACL (resource role on a resource) without `update_users` on that resource | 200; the group holds the resource role there | 403; nothing written; audit line |
| 4 | `group_admin`, `group_moderator` | a group ACL with an empty resource name | 200; a `GroupAcl` with no resource, which breaks every member's need building | 400; nothing written |
| 5 | `group_admin`, `group_moderator` | a role URI not ending in a numeric id | 500 | 400 |
| 6 | `group_moderator` (member), `user_admin` | `PATCH /api2/group/<id>/roles` or `/api2/user/<id>/roles` with `{}` | 200; the target's `Role` rows are deleted for everyone | 200; the target's roles are unlinked, the `Role` rows stay |
| 7 | `role_administrator` | `POST /api2/role` with permissions or a dashboard or alert resource role | 200; the creator is added and holds them | 403; nothing written; audit line |
| 8 | `role_administrator` | `POST /api2/role` with query policies the account does not hold, or with data export when none of its roles exports (N4) | 200; the creator is added and reads that data | 403; nothing written; audit line |
| 9 | `role_administrator`, `role_moderator` (holder) | `PATCH /api2/role/<id>` changing permissions or resource roles (N3) | 200; every holder gains the change | 403; nothing written; audit line |
| 10 | `role_administrator`, `role_moderator` (holder) | `PATCH /api2/role/<id>` adding query policies it does not hold, or turning on data export without exporting itself (N3, N4) | 200 | 403; nothing written; audit line |
| 11 | a non-admin holding `update_permissions` on role (no seeded role does) | `POST /api2/role` with permissions it does not hold | 200; the creator is added | 200; the creator is not added; info line |
| 12 | an admin account using a JWT narrowed to group needs (none is issued today) | attach the admin role, or a role it does not hold, to a group | 200 | 403 |
| 13 | a caller without `create_resource`/`edit_resource` on role | `POST`/`PATCH /api2/role` with an unknown resource role name | 500 (`build_role` ran first) | 403 (Potion's check runs first) |

Unchanged:
- Requests by superusers.
- Roles a caller holds, attached to a group. ACLs on resources the caller may share (`update_users` there).
- Roles and ACLs a group already has, and policies and export a role already has, resent unchanged.
- Role URIs naming no role (still skipped).
- Creating an empty role, or one whose policies and export the creator already holds (the creator is still added).
- Adding a held query policy to a held role. Relabelling a held role.
- **N6:** `PATCH /api2/role/<id>/users` on a held role still confers it on other users (200). On a role the caller does not hold it is still 404. Conferring a role the caller holds is within decision 0004's rule. If the lead wants N6 refused outright, that needs a different rule, for example item-level `update_users` on role.
- **The `/users` self-add:** non-members still get 404 on every group item route.
- Every other route. Every Potion read and list filter (`RoleResourceManager` is untouched).
- Gate failures before the new checks keep their status codes: 401 from `AuthorizedOperation` on the group routes, 403 from the Potion mixin on the role routes. The new refusals are 403 as phase 0h asks. Moving the group routes' 401 to 403 would change today's outcomes for every principal lacking the container permission, so it is left for the FastAPI port (C-10).

Seeded roles with no difference, because they cannot pass any of these route gates: `dashboard_viewer`, `dashboard_editor`, `dashboard_admin`, `directory_reader`, `query_runner`, `user_moderator`, `query_analyst`, `alert_*`, `_default_role`, `data_uploader_*`, `manager`, `data_upload_admin`, `data_catalog_viewer`, `field_setup_viewer`, `entity_matching_viewer`. The same holds for anonymous and public visitors, and for browser-session and render tokens.

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

## Findings for the lead

Outside this WP's scope. Each needs its own decision.

- **F1. User-side grants are unchecked.** `PATCH /api2/user/<id>` resolves role and group URIs and ACLs unfiltered (`build_user_updates`, `update_user_groups`, `update_user_acls`). It is gated only by `edit_user` on site plus `edit_resource` on user. No single seeded non-admin role holds both, but a principal with `manager` and `user_admin`, or a custom role combining them, can make any user, itself included, a site admin, or add users to any group. `held_roles_from_uris` and `verify_acl_grants` apply directly. Suggested follow-up, backend, Sec yes, or fold into WP-5d.
- **F2. The legacy `/roles` sub-routes still cannot add.** `POST`/`PATCH` on `/api2/user/<id>/roles` and `/api2/group/<id>/roles` look up a `ResourceRole` by name, then build `UserRoles`/`GroupRoles` with a `resource_id` column those tables do not have. Every add is a 500. This WP fixed only their deletion of `Role` rows (table row 6). `web/python_client/directory_service/service.py` calls both `PATCH` routes whenever a user's or group's `roles` is set. The JS `DirectoryService.updateUserRoles`/`updateGroupRoles` have no component callers. Recommend fixing or removing the routes together with the python client.
- **F3. `update_roles` on group and user is seeded but never checked.** `group_admin` and `user_admin` hold it; nothing reads it.
- **F4. `create_group` still decides "superuser" from the account** when choosing whose `users` to add. A narrowed admin JWT can therefore set the members of a new group, though only with roles it holds (table row 12). No such token is issued today.

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
  - **`/roles` with `{}`**: 200, and the `Role` rows survive.

## Log

- 2026-10-04 backend-6 unit 1: traced the three escalations through Potion, the managers and the need builder (notes above). Probing the same app also found the group ACL grant and the role PATCH variant. Check: each path reproduced in the unit 2 harness.
- 2026-10-04 backend-6 unit 2: `tests/web/privilege_escalation/` (18 tests: 9 escalation cases, 9 behaviours that must not change). Check: on integration 9 failed, each on `assert 200 == 403` or on the creator being auto-added; 9 passed.
- 2026-10-04 backend-6 unit 3: `web/server/security/grants.py` and the route changes. Check: 19 passed; ruff clean.
- 2026-10-04 backend-6 unit 4: INV-3 table; WP-2b suite at `d1e809a` against integration and this branch. Check: pure layer identical (2517 passed each); live layer differs only in the three pinned escalations.
- 2026-10-05 backend-6 unit 5: `pstack:interrogate` with opus, fable and sonnet; triage above.
- 2026-10-05 backend-6 unit 6: decision 0004 scope and the interrogate fixes. Check: 36 passed here; the same file against integration `3780c8c` gives `22 failed, 14 passed`.

## Evidence

**This WP's tests** (`tests/web/privilege_escalation/`, command under "How to run the tests"):
- this branch: `36 passed`.
- integration `3780c8c` with this branch's test directory copied in: `22 failed, 14 passed`. Each failing case is an escalation or a destructive path this WP closes. The 14 passes are the behaviours that must not change, including N6, the `/users` 404s and the resend cases.
- `test_a_refused_grant_is_audited_with_the_caller` checks that the WARNING line names the caller and the refused role.

**WP-2b suite at `e835c77`**, run in scratch copies built with `git archive`: integration `3780c8c` plus the suite, and this branch's HEAD plus the suite.
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

**Static checks:** `uvx ruff check web/server/security/grants.py tests/web/privilege_escalation` passes; `uvx black -S --check` is clean on both. Edits elsewhere keep each file's existing formatting, and black-version differences in untouched lines are left alone.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
