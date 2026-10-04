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
2. Query-policy filter table: `_construct_authorization_filter` and `restrict_query_filter_to_user_permissions` over harmony_demo plus synthetic hierarchical configs, and `AuthorizedQueryClient.run_query` for non-superusers, superusers and public users (WP-0c request). Since WP-0c, `run_query` takes the filter from `caller_policy_filter` and ANDs it in with `and_policy_filter`; the user-scoped client has no `run_raw_query`, and `/api/field` applies the same filter. Those two paths are tested next to their code (`tests/web/test_authorized_query_client.py`, `tests/web/test_field_info_route.py`). Check: `tests/authz/run.sh`.
3. Need algebra and token narrowing: `QueryNeed` and `DimensionFilter` containment and intersection, `QueryPermission.allows`, `_compute_token_item_needs` and `_compute_token_query_needs`. Check: `tests/authz/run.sh`.
4. Potion permission wiring: the effective needs `ZenysisPrincipalMixin` gives each Potion resource for read, create, update and delete. Check: `tests/authz/run.sh`.
5. Live-stack layer (`tests/authz/http/`): seed drift, per-role users provisioned through the admin API, page and API status codes, Potion list filtering, and the admin self-delete guard. Check: `tests/authz/run.sh -m authz_http` against `tests/authz/stack.sh up`.
6. Findings for security, evidence, `status: review`.

### How to run

```bash
tests/authz/run.sh                     # pure layer, on the root uv project
tests/authz/stack.sh up                # private instance of the WP-2c stack (project harmony-wp2b-authz, port 58660)
eval "$(tests/authz/stack.sh env)"
tests/authz/run.sh -m authz_http       # live-stack layer
tests/authz/stack.sh down
```

`run.sh` is `uv run --with pyyaml==6.0.3 --with hypothesis==6.141.1 pytest tests/authz` on the root uv project (`pyproject.toml`, from WP-2a). That project pins the legacy web stack (Flask 1.0.1, the Flask-Potion fork) on Python 3.9, so this does not use Python 3.13. PyYAML and Hypothesis are added for the run, pinned, until WP-2f folds the suites' extra needs into the dev group. `stack.sh` is a thin wrapper around `tests/contract/stack/stack.sh` (WP-2c): it sets `CONTRACT_PROJECT`, `CONTRACT_WEB_PORT` and `CONTRACT_USERNAME` and re-exports the env under `AUTHZ_*`.

## Contract changes

None. The suite is written against today's Flask path and later re-pointed at `harmony.core.authz.can()` (C-2), which must agree case for case.

## Requests

- [ ] lead: merge after WP-2c. The live layer (`tests/authz/http/`) runs the WP-2c stack through `tests/contract/stack/`, which does not exist on `mig/integration` yet. The pure layer has no such dependency. (blocks the live layer only)

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
- 2026-10-05 qa-3 unit 7: review fixes (qa, reviewer and security all changes-requested). Merged `mig/integration` (root uv project from WP-2a). Potion: split reads (list/item GET go through `identity_get_item_needs` and the SQL list filter) from writes (`can(item)`), gave stand-ins distinct id columns, pinned the alert-notification `read_via` divergence (item check reads the parent PK, never reached over HTTP) and the SQL list-filter column separately, and added a coverage test so every Potion `(operation, type)` pair has a decision row (41 added, mostly `allow: [tag:superuser]`). Rebuilt P3 through a real admin JWT. Escalations: pinned N3 (role_moderator PATCHes its own role), N4 (role create/update attaches all-values policies and dataExport via the `find_by_id` bypass), N5 (group attaches a policy-carrying role), N6 (role `/users` grants to others), and recorded that the `/users` self-add is a 404 from the owner filter, not a refusal. Added the superuser-token-with-query_needs cases, the render routes (N1/N2, outbound renderer mocked), and API-token and admin-via-group token principals. Live layer now wraps the WP-2c stack, refuses a non-loopback base URL, and deletes every user and group it creates. `run.sh` dropped `exec` so the temp files it no longer writes cannot leak; it runs on the root project. Labelled every pinned defect with its finding id and the WP that flips it. Fixed the pylint E1111 (`principals.py` now uses a transient `QueryPolicy`). Check: pure layer `tests/authz/run.sh` gives 4672 passed, 575 skipped; `pylint tests/authz/principals.py` 10.00/10. Fresh stack (`evidence_run.sh`): whole suite with the stack env set 5247 passed (4672 pure + 575 live), then `-m authz_http` twice, 575 and 575. Afterwards the stack held 0 `@authz.invalid` users, 0 groups, 0 `authz*` roles and 0 saved queries, so the cleanup is complete.

## Evidence

- `docs/modernisation/work/WP-2b-evidence/fresh-stack-run.txt`: output of `tests/authz/evidence_run.sh`. It recreates the stack, runs the whole suite with the stack env set, then runs `-m authz_http` twice (the second run shows the live provisioning is idempotent and the cleanup leaves the stack reusable). Counts are in the file header.
- Mutation checks for units 1 to 4 and 7 are in the log above. Every changed expectation failed exactly its own rows and nothing else.
- Hash-seed independence: the pure layer passes under PYTHONHASHSEED 0 to 5 and 123 (unit 2).
- Phase 2b exit check ("every role type in the seed scripts has at least one allow case and one deny case"):
  - `test_every_seeded_role_has_an_allow_and_a_deny` covers the 23 non-admin roles in the pure table.
  - admin's deny cases are `test_admin_cannot_delete_their_own_account` (live) and `render_token:admin` (pure).
- Lead requests answered:
  - WP-0c: `one_source_all_states[header|session]` and `superuser_is_not_filtered`.
  - WP-2a reviewer: Q8, `token_state_exclusion_is_dropped_leaving_no_filter`.
- Not covered, and why:
  - The `query`, `query/granularities` and `query/dimension_values` Potion resources: they need Druid metadata to register.
  - Dashboard, alert and share HTTP flows: decided by `is_authorized`, which the pure table covers.
  - `public_access` on in the live stack: the pure layer covers the identity side (Q2, `anonymous_public`).
- Property-based testing (`test_needs.py`, Hypothesis, already used by WP-2c and WP-2d): a set-model oracle over single-dimension, include-only needs. `&` is set intersection and `required in held` is "held is a superset". A property over the *full* domain (all-values and excludes) would have caught Q3, Q8 and the inverted `CONTAINMENT` row, but it fails on today's `DimensionFilter` algebra, so it is scoped to the well-behaved region and WP-4e, which fixes the algebra, owns widening it.

## Findings for security

Recorded as they behave today. None of them was changed (INV-3). Each names the suite case that pins it, so a fix shows up as a deliberate, reviewed table change.

### Query policy (row-level)

- **Q1. `/api/field/<field_ids>` ran Druid queries with no query policy. Fixed by WP-0c (on `mig/integration`).** `get_field_summaries` (`web/server/routes/views/field.py`) now ANDs `caller_policy_filter()` into each field's filter with `and_policy_filter` and stops sharing the process-wide row-count cache for restricted callers. `AuthorizedQueryClient` no longer has `run_raw_query`. Tested next to the code: `tests/web/test_field_info_route.py` (restricted callers count only their slice and never see another caller's cached counts) and `tests/web/test_authorized_query_client.py`.
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
- **H3. A `role_administrator` can grant themselves any permission except `RoleNeed('admin')`. (High.)** `POST /api2/role` accepts any `permissions`, `dashboardResourceRoleName`, `alertResourceRoleName`, `queryPolicies` and `dataExport`, and `add_current_user_to_role` adds the creator. This bypasses the `update_permissions` gate. `PATCH /api2/role/<id>` (`update_role`) goes through the same `build_role`; that path is pinned as N3. The unique constraint on `role.name` is the only thing that stops this from reaching `RoleNeed('admin')`. `_build_role_needs` grants superuser to any role whose *name* is `admin`, and `create_role` derives the name from the label (`label.lower().replace(' ', '_')`), so the label `Admin` collides with the seeded row. Pinned by `test_role_administrator_grants_itself_any_permission_through_a_new_role`.
- **H4. Saved queries have no owner check.** Any signed-in user reads any `/api2/user_query_session/<uuid>` (all 24 seeded roles get 200, anonymous gets 401). `POST /api2/user_query_session/generate_link` stores whatever `userId` the client sends. Pinned by `test_saved_queries.py`.
- **H5. The user list hides only users who hold the admin role directly.** `UserResourceManager` filters on `user.roles`, so a user who is admin through a group shows up in non-admins' lists. Seen while running H1; not pinned, because a fixture admin-through-group user would also hit H1.
- **H6. Not authorisation, but these block testing.** `GET /api2/user_query_session` and `GET /api2/dashboard_session` return 500 for everyone (`'Pagination' object is not iterable`). `POST /api2/user/<id>/roles` returns 500 (`role.permissions[0]` on a missing role). The suite reads saved queries item by item and assigns roles through `PATCH /api2/user/<id>`.
- **Admin's deny case** (phase 2b exit check): `test_admin_cannot_delete_their_own_account` gives 400. A `user_admin` cannot change roles through the user form, because that needs SITE `edit_user`, so the response is 401 (`test_user_admin_cannot_change_roles_through_the_user_form`).

### New findings from the security review (N1 to N6; decision 0004)

Added in unit 7, pinned as today's behaviour.

- **N1. Unauthenticated dashboard thumbnail render.** `/dashboard/<slug>/png/thumbnail` (`web/server/routes/page_renderer.py`) has no authentication or authorisation. The server mints a render-bot JWT (the render bot is a site admin) and renders the dashboard for an anonymous caller. The PDF and JPEG routes do require `view_resource`. Owner WP-0i. Pinned by `test_render_routes.py` (the outbound renderer is mocked; urlbox is never called).
- **N2. Render-bot thumbnails served to policy-restricted viewers.** `/api2/storage/retrieve` renders the thumbnail under the render bot's token with every query need and caches it on the slug alone, so a viewer whose policy restricts them gets the same image. Owner WP-0i, then WP-1h. Pinned by `test_stored_thumbnail_is_rendered_by_the_render_bot_and_shared`.
- **N3. `role_moderator` adds any permission to a role it holds.** `PATCH /api2/role/<id>` on a held role, via `build_role`. Owner WP-0h. Pinned by `test_role_moderator_adds_a_permission_to_a_role_it_holds`.
- **N4. Role create/update attaches all-values query policies and `dataExport`.** `build_role` resolves query-policy URIs with `find_by_id`, bypassing `QueryPolicyResourceManager`, so a `role_administrator` can attach `/api2/query_policy/1` and `/2` and lift its own row-level filter. Owner WP-0h. Pinned by `test_role_administrator_attaches_all_values_policies_and_data_export`.
- **N5. A group attaches a policy-carrying role.** A `group_moderator` can attach `_default_role` (all-values policies) to its group and gain them. Owner WP-0h. Pinned by `test_group_moderator_gains_all_values_policies_by_attaching_a_role`.
- **N6. `PATCH /api2/role/<id>/users` grants a held role to others.** A `role_moderator` can add any user to a role it holds. Owner WP-0h. Pinned by `test_role_moderator_grants_a_role_it_holds_to_another_user`; verified through the admin view because the grantee's identity is cached for up to 10 minutes.
- The `/users` self-add that decision 0004 lists is **not reachable**: the group item routes resolve through `GroupResourceManager._query` (own groups only), so a non-member moderator gets 404 before the sitewide check. The reachable group_moderator path is a member editing its group's roles (H2 / N5). Pinned by `test_group_moderator_cannot_reach_a_group_it_is_not_a_member_of`.

Two more, found by calling the production functions, pinned as today:

- **Alert `read_via`.** `AlertNotificationResource` read: the SQL list filter joins on the parent alert definition's `authorization_resource_id` (correct), but the item-level check (`HybridRelationshipNeed.__call__`) reads the parent's own primary key. No HTTP path evaluates the item check today. Owner accept until WP-5f; WP-4e's `can()` models it as the parent alert's resource. Pinned by `test_alert_notification_item_check_uses_the_parent_primary_key`.
- **Superuser tokens ignore their own `query_needs`.** A `needs: ['*']` token keeps `RoleNeed('admin')`, so its `query_needs` never reach the filter and the query is unfiltered. Owner WP-4e; issuance WP-5d. Pinned by `superuser_token_ignores_its_own_query_needs` and `..._via_group_...`.

### Security triage (from the WP-2b security review, 2026-10-05)

Owners are the WPs that resolve each finding; "accept until phase N" means recorded and carried, no change in this WP.

| ID | Severity | Owner | Note |
|---|---|---|---|
| Q1 | High | 0c | `/api/field` counts and dates outside the policy; fixed by WP-0c (merged to integration); tested in `tests/web/test_field_info_route.py` |
| Q2 | Medium | 4e | Public access gives any-Referer anonymous callers the whole datasource; human decides; public principal needs an explicit scope |
| Q3 | Low | 4e | Token excludes lost, fails closed; no issuer |
| Q4 | Low | 4e | Docstring and code disagree on claim keys; needs a claim schema rejecting unknown keys |
| Q5 | Low | 4e | Narrows in the intended direction; define in token_scopes |
| Q6 | Low | 4e | Hash-seed-dependent order; only admin explicit-needs token |
| Q7 | Low | 4e | Dead code; do not port |
| Q8 | Low | 4e | Wrong AND algebra; bounded by the account; 4e fixes the algebra |
| I1 | Medium | 5d | Every signed-in user sees all users' emails, phones, ACLs, token ids; phase-0 strip optional |
| I2 | Low | accept until 5f | Alert roles never reach `alert_definitions`; fails closed |
| I3 | Low | 5d | Permissions seeded on the wrong resource type; fails closed |
| I4 | Low | 4e | Correct narrowing; keep the pin |
| I5 | Low | 4e | Id 0 becomes a sitewide check; unreachable; use typed ids |
| P1 | Medium | accept until 5f/5b | No item permission on six resources; `POST /api2/share/email` is an open mail relay |
| P2 | Low | 5d | Meta permission overrides have no effect; Potion goes in 5d |
| P3 | Low | 4e | 3-dimension `QueryNeed` makes list filtering raise; no issuer |
| P4 | Low | accept until 5h | Page denials return 200 |
| H1 | High | 0h | `group_admin` becomes site admin (reproduced) |
| H2 | High | 0h | `group_moderator` becomes site admin (reproduced) |
| H3 | High | 0h | `role_administrator`; scope adds the PATCH path and policies/dataExport (N3, N4) |
| H4 | Low | accept until 5b | Saved queries readable, attribution forgeable |
| H5 | Low | 5d | Admins-via-group appear in non-admins' user lists (part of I1) |
| H6 | Low | accept until phase 5 | 500s; trap: fixing list endpoints without an owner filter exposes every saved query and session |
| Alert read_via | Low | accept until 5f | Item check uses the parent PK, never called; HTTP reads use the correct column |
| Notification values | Medium | accept until 5f | Not filtered by the reader's query policy (`alerts_api_models.py:236-238`) |
| N1 | High | 0i | Unauthenticated thumbnail render with render-bot admin scope |
| N2 | High | 0i, then 1h | Render-bot thumbnails served to policy-restricted viewers |
| N3 | High | 0h | `role_moderator` PATCHes its own role to any permission (reproduced) |
| N4 | High | 0h | Role create/update attaches all-values policies via the `find_by_id` bypass; `dataExport` too (reproduced) |
| N5 | High | 0h | Group attaches a policy-carrying role (reproduced) |
| N6 | Medium | 0h | `PATCH /api2/role/<id>/users` grants a held role to others (reproduced) |
| Superuser token | Low | 4e (issuance 5d) | `needs: ['*']` tokens ignore their own `query_needs` |

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-04 | 2026-10-04 qa-2b-review at ca58b7d: pure layer 4672 passed and 575 skipped under two seeds on the branch and on a merge with integration 215f03b plus WP-2c fa72fe0; live layer 575 twice on a fresh stack (5247 with the stack env), zero authz residue; read_via now discriminated (seven potion.yaml mutations each fail exactly the right tests); seed drift covers roles and resource roles (three live mutations each fail one test); run.sh fixed; evidence numbers reproduced. Low: evidence_run.sh:5 lacks -e so a failed stack up runs the live tests against whatever listens on the port; WP-2b.md:80-81 wording wrong about counts and unit 7 mutation checks, have evidence_run.sh print leftover counts; QA MEMORY.md conflicts with integration (keep both entries). |
| reviewer | changes-requested | 2026-10-04 | 2026-10-04 rev-2b at ca58b7d: six of eight closures hold; Potion agreement now real (four potion.yaml mutations each fail the right tests); pure layer 4672 passed in 5.5 s, also under a trial merge with integration 215f03b and WP-2f's locked env; no production code. Fix: N5 pin asserts policies through the admin (superuser sees all rows) so only the status discriminates, assert through the actor or the group's roles (test_escalation.py:111-115); N4 pins create only, add a PATCH variant attaching query_policy 1 and 2 and dataExport true (:149-242); test_needs.py:86-93 disjoint branch accepts an all_values filter, assert equals need(d=[]) and fix the comment; Q2 Q3 Q4 Q5 Q8 and I1 rows lack finding ids and owner WPs (4e, 5d); principals.yaml:88-89 claims an API-token revocation check that does not exist; merge integration (base 246 commits behind: run_raw_query gone, policy on /api/field, caller_policy_filter and and_policy_filter names), update the plan and drop the .hypothesis request; nits: unused potion item_ids 42/5/3 (assert each remaining item_id is held as a write need), evidence claims at WP-2b.md:80-81, evidence_run.sh label and the N2 docstring. |
| security | changes-requested | 2026-10-04 | 2026-10-04 sec-2b re-review at ca58b7d: closures verified on a fresh private WP-2c stack (5247 passed with stack env, live layer 575 again; no authz residue; loopback guard refuses example.com, userinfo tricks, nip.io and localhost.evil; superuser-token query_needs cases present; alert read_via pinned; thumbnail claim fixed; render routes covered with the outbound call mocked; session, render and API-token principals added); semgrep p/python p/flask p/security-audit p/secrets and Trail of Bits clean bar one loopback false positive; token-leak rules 10 false positives. Fix (reproduced live): F1 N5 pin's policy assertion reads the admin's full list and can never fail, assert the group's roles via admin GET and the actor's own GET /api2/query_policy before and after; F2 N4 pins create only, PATCH /api2/role/id with query_policy 1 and 2 plus dataExport true gives 200 for role_moderator and role_administrator, add the PATCH pin; F3 the /roles empty-map deletion (group and user routes, 200 and the Role row gone for everyone incl. a bystander) is unpinned though decision 0004 point 3 requires it; F4 N6 label should read pending lead ruling, WP-0h proposes no change; F5 principals.yaml:88-89 revocation comment wrong (owner 5d C-5); F6 optional pins for WP-0i N7, share_via_email URL and WP-0h rows 3-4; F7 run.sh fetches hypothesis unpinned. Triage table updated in the review. |
