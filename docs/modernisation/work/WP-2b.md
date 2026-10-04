---
wp: "2b"
title: "Permission and policy suite"
status: building
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

## Evidence

## Findings for security

Recorded as they behave today. None of them was changed (INV-3). Each names the suite case that pins it, so a fix shows up as a deliberate, reviewed table change.

### Query policy (row-level)

- **Q1. `/api/field/<field_ids>` runs Druid queries with no query policy.** `FieldsApi.get_field_summary` (`web/server/routes/views/field.py:83-110`) calls `druid_context.data_time_boundary.get_field_time_boundary` and `row_count_lookup.get_row_count`, which run through the system client's `run_raw_query` (`web/server/data/time_boundary.py`, `web/server/data/row_count.py:25`). So any signed-in user gets row counts and time boundaries for any field, outside their policy. `/api/dimension_info` behaves the same way. WP-0c is fixing `/api/field`. This suite pins the fixed behaviour once WP-0c lands. Until then, `AuthorizedQueryClient.run_raw_query` is deliberately not tested.
- **Q2. Public access lifts every row-level restriction.** With `public_access` on, an anonymous visitor's queries skip the policy filter entirely (`apply_authorization_filters`, `query_policy.py:63`). Case: `anonymous_with_public_access_is_not_filtered`.
- **Q3. Token `exclude_values` are never enforced, and they cost the token every other dimension.** `{source: {exclude_values: [S9]}}` intersects with an all-values account need into plain all-values. `DimensionFilter.__and__` drops excludes, and `_construct_single_filter` skips excludes on all-values entries. The other authorizable dimensions are lost, so the result is deny-all. Case: `token_exclude_values_are_dropped_and_other_dimensions_lost`.
- **Q4. The `_install_token_needs` docstring documents `included_values` and `excluded_values`, but the code reads `include_values` and `exclude_values`.** A token built from the docstring is read as all values. Case: `token_docstring_key_included_values_is_read_as_all_values`.
- **Q5. A superuser holding an explicit-needs token loses `RoleNeed('admin')`.** Their query policy then comes from the token's `query_needs`. Export render tokens use `'*'`, which gives all values, so admin renders stay unrestricted. Case: `render_token_for_admin_is_filtered_by_token_query_needs`.
- **Q6. `_construct_hierarchical_filter` depends on `PYTHONHASHSEED` when a hierarchical need carries excludes.** It mixes `|=` and `&=` in dict order. Database policies never carry excludes, so only explicit JWT `query_needs` reach it. Not pinned: the output is non-deterministic.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
