---
wp: "2b"
title: "Permission and policy suite"
status: review
owner_role: "qa"
instances:
  - name: "qa-3"
    files: ["tests/authz/**"]
branch: "mig/WP-2b-authz-suite"
requirements: [INV-3, QA-4, SEC-4]
contracts_consumed: [C-2]
contracts_changed: []
security_review: true
---

# WP-2b: Permission and policy suite

## Plan

Units, in order. Each line names the change and the check that ends it.

The suite records what the Flask path decides today. Later it is pointed at `harmony.core.authz.can()` (C-2), which must agree case for case. It has two layers:
- **Pure.** No server, database or Druid. Identities come from the production need-building code (`BaseUserMixin.enumerate_permissions`, then `signal_handlers.on_identity_loaded`, including JWT narrowing). Only the rows that code reads are replaced: roles, groups, ACLs, the configuration store and JWT claims.
- **Live stack.** Marked `authz_http`, skipped unless `AUTHZ_BASE_URL` is set. Covers what only HTTP can reach: Potion list filtering, manager filters, decorator status codes, and seed drift.

1. Principal builder plus the `is_authorized` decision table: every seeded role and the special principals (anonymous, public, ACL holders, group members, browser sessions, render tokens) against every check the app makes. Check: `tests/authz/run.sh`.
2. Query-policy filter table: `_construct_authorization_filter` and `restrict_query_filter_to_user_permissions` over harmony_demo plus synthetic hierarchical configs, and `AuthorizedQueryClient.run_query` for non-superusers, superusers and public users (WP-0c request). `run_raw_query` is deliberately not tested while WP-0c decides it. Check: `tests/authz/run.sh`.
3. Need algebra and token narrowing: `QueryNeed` and `DimensionFilter` containment and intersection, `QueryPermission.allows`, `_compute_token_item_needs` and `_compute_token_query_needs`. Check: `tests/authz/run.sh`.
4. Potion permission wiring: the effective needs `ZenysisPrincipalMixin` gives each Potion resource for read, create, update and delete. Check: `tests/authz/run.sh`.
5. Live-stack layer (`tests/authz/http/`): seed drift, per-role users provisioned through the admin API, page and API status codes, Potion list filtering, and the admin self-delete guard. Check: `tests/authz/run.sh -m authz_http` against `tests/authz/stack.sh up`.
6. Findings for security, evidence, `status: review`.

### How to run

```bash
tests/authz/run.sh                     # pure layer: uv, Python 3.8, the pinned web requirements
tests/authz/stack.sh up                # private copy of the WP-2c stack (project harmony-wp2b-authz, port 58660)
eval "$(tests/authz/stack.sh env)"
tests/authz/run.sh -m authz_http       # live-stack layer
tests/authz/stack.sh down
```

`run.sh` rewrites the `-e git+...` lines in `requirements*.txt` into direct references, because `uv run --with-requirements` rejects editable lines, then runs `uv run --no-project -p 3.8 --with-requirements <rewritten> --with 'pytest<8' --with pyyaml --with requests python -m pytest tests/authz`. The web stack pins Python 3.8, so this does not use Python 3.13. `stack.sh` needs `tests/contract/stack/` from WP-2c.

## Contract changes

None. The suite is written against today's Flask path and later re-pointed at `harmony.core.authz.can()` (C-2), which must agree case for case.

## Requests

## Log

- 2026-10-04 qa-3 unit 1: principal builder (`principals.py`, `principals.yaml`, `seed.yaml` captured from a freshly migrated harmony_demo DB) and the `is_authorized` table (`decisions.yaml`: 57 checks x 41 principals). Check: `tests/authz/run.sh` gives 2338 passed. Mutation check: dropping `role:manager` from `view_admin_page` and narrowing `view_resource user` to superusers gave 39 failures, one per changed row.
- 2026-10-04 qa-3 unit 2: query-policy table (`query_policies.yaml`, 31 cases, 52 runs). Each case goes through `AuthorizedQueryClient.run_query` into a recording Druid client. Cases without explicit token claims run under both header auth and browser-session narrowing. Configurations: harmony_demo, plus synthetic two-level hierarchy, flat and no-authorizable-dimension configs. This answers the WP-0c request: `one_source_all_states[header|session]` shows a non-superuser's policy filter ANDed into the Druid query, and `superuser_is_not_filtered` and `superuser_via_group_is_not_filtered` show a superuser's query reaching Druid unchanged. Check: `tests/authz/run.sh` gives 2391 passed under PYTHONHASHSEED 0 to 5 and 123. Mutation check: changing `one_source_all_states` to `expect: null` failed 3 runs.
- 2026-10-04 qa-3 unit 3: need algebra and token narrowing (`test_needs.py`). Covers `QueryNeed` containment (12 rows) and intersection (7 rows), and `QueryPermission.allows` (5 rows). For every signed-in principal it checks that a browser session keeps exactly the account's item needs (33 principals). It also covers explicit-token item narrowing (7 rows). Check: `tests/authz/run.sh` gives 2455 passed. Mutation check: flipping one containment row and one token row failed exactly those 2.
- 2026-10-04 qa-3 unit 4: Potion wiring (`potion.yaml`, `test_potion.py`). All 23 non-query `/api2` resources are registered on a bare `Api` through the real `list_all_resource_types`. The tests check:
  - every resource is classified, as one of 17 permission-wired and 6 unprotected;
  - the exact standard and hybrid needs per CRUD method;
  - for all 41 principals, Potion's `HybridPermission.can()` agrees with `is_authorized` on every resource and method, sitewide and per item;
  - the three-dimension `QueryNeed` crash.

  Check: `tests/authz/run.sh` gives 2516 passed. Mutation check: a wrong id attribute and a wrong `read_via` type failed exactly those 2 resources.
- 2026-10-04 qa-3 unit 5: live-stack layer (`tests/authz/http/`, marker `authz_http`; skipped unless `AUTHZ_BASE_URL` is set). It provisions one user per seeded role through the admin API, with a per-run password that is never stored. It covers:
  - seed drift against `seed.yaml`;
  - page and `/api2` outcomes for 24 roles plus an anonymous visitor (`requests.yaml`);
  - Potion list filtering;
  - escalations H1 to H3;
  - saved-query exposure;
  - admin's self-delete deny.

  Check: fresh stack (`stack.sh down && up`), then the whole suite gives 3085 passed. Running the live-stack layer twice more gives 569 passed each time, so provisioning is idempotent.
- 2026-10-04 qa-3 unit 6: lead requests. Added `token_state_exclusion_is_dropped_leaving_no_filter` (Q8, reported by the WP-2a reviewer), and noted the admin-role convention and the WP-0h hand-off under H. Check: `tests/authz/run.sh -k token_` gives 14 passed. The full pure layer is re-run below.

## Evidence

- `docs/modernisation/work/WP-2b-evidence/fresh-stack-run.txt`: output of `tests/authz/evidence_run.sh`. It recreates the stack, runs the whole suite with the stack env set (3085 passed), then runs `-m authz_http` twice (569 passed, then 569 passed).
- Mutation checks for units 1 to 4 are in the log above. Every changed expectation failed exactly its own rows and nothing else.
- Hash-seed independence: the pure layer passes under PYTHONHASHSEED 0 to 5 and 123 (unit 2).
- Phase 2b exit check ("every role type in the seed scripts has at least one allow case and one deny case"):
  - `test_every_seeded_role_has_an_allow_and_a_deny` covers the 23 non-admin roles in the pure table.
  - admin's deny cases are `test_admin_cannot_delete_their_own_account` (live) and `render_token:admin` (pure).
- Lead requests answered:
  - WP-0c: `one_source_all_states[header|session]` and `superuser_is_not_filtered`.
  - WP-2a reviewer: Q8, `token_state_exclusion_is_dropped_leaving_no_filter`.
- Not covered, and why:
  - `AuthorizedQueryClient.run_raw_query`: WP-0c is deciding it.
  - The `query`, `query/granularities` and `query/dimension_values` Potion resources: they need Druid metadata to register.
  - Dashboard, alert and share HTTP flows: decided by `is_authorized`, which the pure table covers.
  - `public_access` on in the live stack: the pure layer covers the identity side (Q2, `anonymous_public`).
- Property-based testing: `QueryNeed` intersection has a natural invariant, `(a & b) in a and (a & b) in b` for include-only needs. Hypothesis is not a project dependency, so adding it is left to the lead.

## Findings for security

Recorded as they behave today. None of them was changed (INV-3). Each names the suite case that pins it, so a fix shows up as a deliberate, reviewed table change.

### Query policy (row-level)

- **Q1. `/api/field/<field_ids>` runs Druid queries with no query policy.** `FieldsApi.get_field_summary` (`web/server/routes/views/field.py:83-110`) calls `druid_context.data_time_boundary.get_field_time_boundary` and `row_count_lookup.get_row_count`, which run through the system client's `run_raw_query` (`web/server/data/time_boundary.py`, `web/server/data/row_count.py:25`). So any signed-in user gets row counts and time boundaries for any field, outside their policy. `/api/dimension_info` behaves the same way. WP-0c is fixing `/api/field`. This suite pins the fixed behaviour once WP-0c lands. Until then, `AuthorizedQueryClient.run_raw_query` is deliberately not tested.
- **Q2. Public access lifts every row-level restriction.** With `public_access` on, an anonymous visitor's queries skip the policy filter entirely (`apply_authorization_filters`, `query_policy.py:63`). Case: `anonymous_with_public_access_is_not_filtered`.
- **Q3. Token `exclude_values` are never enforced, and they cost the token every other dimension.** `{source: {exclude_values: [S9]}}` intersects with an all-values account need into plain all-values. `DimensionFilter.__and__` drops excludes, and `_construct_single_filter` skips excludes on all-values entries. The other authorizable dimensions are lost, so the result is deny-all. Case: `token_exclude_values_are_dropped_and_other_dimensions_lost`.
- **Q4. The `_install_token_needs` docstring documents `included_values` and `excluded_values`, but the code reads `include_values` and `exclude_values`.** A token built from the docstring is read as all values. Case: `token_docstring_key_included_values_is_read_as_all_values`.
- **Q5. A superuser holding an explicit-needs token loses `RoleNeed('admin')`.** Their query policy then comes from the token's `query_needs`. Export render tokens use `'*'`, which gives all values, so admin renders stay unrestricted. Case: `render_token_for_admin_is_filtered_by_token_query_needs`.
- **Q6. `_construct_hierarchical_filter` depends on `PYTHONHASHSEED` when a hierarchical need carries excludes.** It mixes `|=` and `&=` in dict order. Database policies never carry excludes, so only explicit JWT `query_needs` reach it. Not pinned: the output is non-deterministic.
- **Q7. `QueryPermission` and `AuthorizedQuery` have no callers.** No query is gated on a `QueryNeed` superset check today. Row-level authorisation is only the filter injection in `AuthorizedQueryClient.run_query`. `test_query_permission` records the dead semantics in case a port revives them.
- **Q8. A token's state exclusion is dropped, and the token ends up unrestricted. (Reported by the WP-2a reviewer.)**
  - **Reproduce:** take an account whose policies allow all values of `source` and `StateName`. Sign in with JWT claims `{needs: ['*'], query_needs: [{StateName: {exclude_values: [Pará]}, source: {}}]}`.
  - **Result:** Druid receives no authorisation filter at all, so Pará stays visible.
  - **Cause:** `_compute_token_query_needs` intersects the token need with each account need. `DimensionFilter.__and__` (`models/python/permissions.py:211-218`) handles two all-values filters by intersecting their exclude lists. The account's exclude list is empty, so the intersection is empty and the exclusion is lost.
  - This is the case where every dimension appears in the token. Compare Q3, which loses the exclusion and denies everything instead.
  - Pinned by `token_state_exclusion_is_dropped_leaving_no_filter`.

### Item permissions (`is_authorized`, `decisions.yaml`)

- **I1. Every signed-in user can read every user, group, role, resource, configuration and query policy.** They hold sitewide `view_resource` on all of these (`install_default_user_permissions`). Potion's manager filters narrow groups, roles and policies to the user's own and hide admins from the user list. Users and resources are not narrowed: the user list inlines ACLs, API token ids and roles, and the resource list names every dashboard and alert. Rows: `*|view_resource|user|allow`, `*|view_resource|resource|allow`.
- **I2. Seeded alert roles never grant Potion access to alert definitions.** `alert_resource_role` yields needs of type `alert` only. Potion checks `alert_definitions`. So `role:alert_admin` passes the `/alerts` page and the create gate, but is denied listing, reading and creating alert definitions unless it holds a per-alert ACL. Rows: `role:alert_admin|view_resource|alert_definitions|deny`, `role:alert_creator|create_resource|alert|allow`, `role:alert_creator|create_resource|alert_definitions|deny`.
- **I3. Some seeded permissions are on the wrong resource type for the check that reads them.** `user_admin` and `user_moderator` hold USER `invite_user`, but the invite route checks SITE `invite_user`. `manager` holds SITE `reset_password`, but the reset route checks USER `reset_password`. Nobody but admin holds `change_password`, so users cannot change their own password through `/api2/user/<id>/password`. Rows: `role:user_admin|invite_user|site|deny`, `role:manager|reset_password|user:43|deny`, `*|change_password|user:42|deny`.
- **I4. A sitewide token need narrows to the account's per-item needs.** A token claiming `[view_resource, null, dashboard]` for a dashboard owner keeps only `view_resource` on dashboard 7. The token cannot widen the account, which is the intended direction. Row: `test_explicit_token_item_needs[dashboard_owner-...]`.
- **I5. `is_authorized` converts the id with `int(resource_id) if resource_id else None`.** So id `0` becomes a sitewide check. Resource ids start at 1, so this is not reachable today.

### Potion wiring (`potion.yaml`)

- **P1. Six `/api2` resources have no item-level permission.** They are `share`, `metadata`, `data_digest`, `user_query_session`, `storage` and `dashboard_session`. Signing in is the only gate. With public access on, an anonymous request with any `Referer` header also passes. `user_query_session` and `dashboard_session` are plain `ModelResource`s, so any signed-in user can list every saved query (`userId`, `queryBlob`) and every dashboard session. Pinned by `test_unprotected_resources_have_no_item_permissions`.
- **P2. Meta `permissions` overrides of `read`, `create`, `update` and `delete` are dead.** `ZenysisPrincipalMixin._permissions` always rewires them to the `*_resource` permissions. `UserResource` and `ConfigurationResource` declare `{read: yes}`, but reads are allowed only through the default sitewide `view_resource` every signed-in user holds. Public anonymous visitors cannot read configuration. Pinned by `test_method_permissions[UserResource|ConfigurationResource]`.
- **P3. A `QueryNeed` over exactly three dimensions makes Potion list filtering raise `TypeError`.** `HybridItemNeed.identity_get_item_needs` matches needs to a 3-tuple prototype by `len()`. The only way to get one is an admin account using a token with an explicit `needs` list, which drops `RoleNeed('admin')`, and a three-dimension composite `query_needs` entry, which is kept verbatim for superusers. Pinned by `test_three_dimension_query_need_breaks_potion_list_filtering`.
- **P4. Some decisions are only visible over HTTP.** Page routes deny by rendering the unauthorized page with status 200, not 401 or 403. `/api2` denies an anonymous visitor with 401. A non-admin reading an invisible item gets 404. `requests.yaml` records all three as outcomes (`page:unauthorizedPage`, `401`, `404`).

### Live stack (`tests/authz/http/`)

The admin role is `/api2/role/1` by convention: the migrations seed it first, with id 1 and name `admin` (`seed.yaml`, checked by `test_seed.py`). Nothing in the code refers to the id. Superuser status comes from the role *name* (`_build_role_needs`, `User.is_superuser()`), so any role named `admin` would be a superuser role. H1 and H2 attach that row. H3 is held back only by the name being unique. WP-0h (decision 0003) closes H1 to H3. When it is ready, these three tests change to expect 403 on the WP-0h branch, and not before.

- **H1. A `group_admin` can make themselves site admin. (Critical.)** Run `POST /api2/group {"$uri": "", "name": "x", "roles": ["/api2/role/1"], "users": [], "acls": []}`. A non-superuser creator is added as the group's only member, so they inherit `RoleNeed('admin')`. `GET /admin` then renders the admin page. The cause is that `build_group` resolves role URIs with `Transaction.find_by_id`, which bypasses the `RoleResourceManager` filter, and nothing refuses the admin role. Pinned by `test_group_admin_becomes_site_admin_by_creating_a_group_with_the_admin_role`.
- **H2. A `group_moderator` who belongs to any group can make themselves site admin. (Critical.)** `PATCH /api2/group/<id>` with `roles: [admin]` only needs sitewide `edit_resource` on group. Pinned by `test_group_moderator_becomes_site_admin_through_a_group_it_belongs_to`.
- **H3. A `role_administrator` can grant themselves any permission except `RoleNeed('admin')`. (High.)** `POST /api2/role` accepts any `permissions`, `dashboardResourceRoleName`, `alertResourceRoleName`, `queryPolicies` and `dataExport`, and `add_current_user_to_role` adds the creator. This bypasses the `update_permissions` gate. By reading the code, `PATCH /api2/role/<id>` (`update_role`) goes through the same `build_role`; that path is not pinned. The unique constraint on `role.name` is the only thing that stops this from reaching `RoleNeed('admin')`. `_build_role_needs` grants superuser to any role whose *name* is `admin`, and `create_role` derives the name from the label (`label.lower().replace(' ', '_')`), so the label `Admin` collides with the seeded row. Pinned by `test_role_administrator_grants_itself_any_permission_through_a_new_role`.
- **H4. Saved queries have no owner check.** Any signed-in user reads any `/api2/user_query_session/<uuid>` (all 24 seeded roles get 200, anonymous gets 401). `POST /api2/user_query_session/generate_link` stores whatever `userId` the client sends. Pinned by `test_saved_queries.py`.
- **H5. The user list hides only users who hold the admin role directly.** `UserResourceManager` filters on `user.roles`, so a user who is admin through a group shows up in non-admins' lists. Seen while running H1; not pinned, because a fixture admin-through-group user would also hit H1.
- **H6. Not authorisation, but these block testing.** `GET /api2/user_query_session` and `GET /api2/dashboard_session` return 500 for everyone (`'Pagination' object is not iterable`). `POST /api2/user/<id>/roles` returns 500 (`role.permissions[0]` on a missing role). The suite reads saved queries item by item and assigns roles through `PATCH /api2/user/<id>`.
- **Admin's deny case** (phase 2b exit check): `test_admin_cannot_delete_their_own_account` gives 400. A `user_admin` cannot change roles through the user form, because that needs SITE `edit_user`, so the response is 401 (`test_user_admin_cannot_change_roles_through_the_user_form`).

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | changes-requested | 2026-10-05 qa-2b-review: 2517 no-server tests under two seeds, 569 live twice on a fresh stack, characterisation on integration, discrimination flips and H1 by hand all reproduced. Fix: potion.yaml:33 read_via id for alert notifications is wrong (Potion checks AlertDefinition.id, not authorization_resource_id) and the agreement test is blind to it (production consequence: alert ACLs keyed on Resource.id govern notifications of whichever alert definition shares that pk); stack.sh needs WP-2c's :local image (undocumented); run.sh exec defeats the trap (temp leak); seed drift check partial; stale evidence numbers. |
| reviewer | pending | |
| security | pending | |
