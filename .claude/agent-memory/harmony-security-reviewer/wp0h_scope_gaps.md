---
name: wp0h-scope-gaps
description: Escalation paths beyond WP-2b's H1-H3 that WP-0h must close and pin (live-confirmed 2026-10-04); check them when reviewing WP-0h
metadata:
  type: project
---

Confirmed on a private harmony_demo stack during the WP-2b review (2026-10-04):
- A `role_moderator` (sitewide `edit_resource` on role) PATCHes a role it holds (`PATCH /api2/role/<own id>`, `update_role` -> `build_role`), adds `view_admin_page`, and `/admin` renders. This affects every holder of that role.
- A `role_administrator` POSTs a role whose `queryPolicies` list the existing all-values policies (`/api2/query_policy/1` source:null and `/2` StateName:null, seeded for `_default_role`). `build_role` resolves them with `find_by_id`, bypassing `QueryPolicyResourceManager`. The creator is auto-added and its row-level filter disappears. Entries need `$uri`, `dimension`, `dimensionValue` and `queryPolicyTypeId`, or the schema returns 400.
- A `group_moderator` attaches `_default_role` to its group and gains the all-values policies. A refusal rule limited to "admin role or resource roles" misses this.

**Why:** the phase-0 0h text names only "permissions or resource roles" and the admin role, so a fix could close the POST case alone and still pass the three flipped WP-2b tests.
**How to apply:** when reviewing WP-0h, require the INV-3 table and pinned refusals for PATCH by role_moderator, `queryPolicies`/`dataExport` on role create/update, and group attach of any role whose grants exceed the caller's. Also check `PATCH /api2/role/<id>/users` (code-read only: `edit_resource` on a held role lets the caller add others).

Related: [[render-bot-is-site-admin]]
