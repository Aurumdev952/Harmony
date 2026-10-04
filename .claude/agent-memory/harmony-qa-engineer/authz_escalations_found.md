---
name: authz-escalations-found
description: WP-2b pinned live privilege escalations (H1-H3, N3-N6) to admin; any WP touching group/role APIs changes those tests deliberately
metadata:
  type: project
---

WP-2b found seven privilege escalations on main and pinned them in `tests/authz/http/test_escalation.py`, as current behaviour (INV-3). Owner WP-0h (decisions 0003 and 0004):
- H1 `group_admin` creates a group carrying the admin role.
- H2 `group_moderator` patches its own group's roles to admin.
- H3 `role_administrator` creates a role with any permissions and is auto-added.
- N3 `role_moderator` PATCHes a role it holds to add any permission.
- N4 role create/update attaches all-values query policies and `dataExport` (the `build_role` `find_by_id` bypass).
- N5 `group_moderator` attaches a policy-carrying role (`_default_role`) to its group.
- N6 `PATCH /api2/role/<id>/users` grants a held role to others.

N1/N2 (render routes) are owner WP-0i and pinned in `tests/authz/test_render_routes.py`.

**Why:** INV-3 says authorisation decisions never change silently. A fix has to be a security-reviewed WP that flips these tests on purpose.

**How to apply:** When reviewing a WP that touches group or role APIs, `build_group`, `build_role` or `add_current_user_to_role`:
- If these tests fail, the fix is legitimate only if the WP records it and has a security verdict.
- If they still pass after a WP that claims to close an escalation, the fix did not work.

Related: [[authz-suite-harness]]
