---
name: authz-escalations-found
description: WP-2b pinned live privilege escalations (H1-H3, N3-N6, /roles empty map) and render-route pins (N1, N2, N7); any WP touching group/role APIs or page_renderer changes those tests deliberately
metadata:
  type: project
---

WP-2b found privilege escalations on main and pinned them in `tests/authz/http/test_escalation.py`, as current behaviour (INV-3). Owner WP-0h (decisions 0003 and 0004; WP-0h INV-3 table rows in brackets):
- H1 `group_admin` creates a group carrying the admin role (row 1).
- H2 `group_moderator` patches its own group's roles to admin (row 2).
- H3 `role_administrator` creates a role with any permissions and is auto-added (row 7).
- N3 `role_moderator` PATCHes a role it holds to add any permission (row 9).
- N4 role create (row 8) and update (row 10) attach all-values query policies and `dataExport` (the `build_role` `find_by_id` bypass).
- N5 `group_moderator` attaches a policy-carrying role (`_default_role`) to its group (row 2).
- `/roles` empty map: `PATCH /api2/group|user/<id>/roles {}` deletes the Role rows for every holder (row 6).
- N6 `PATCH /api2/role/<id>/users` grants a held role to others. Lead ruled no change (decision 0004 rule 1, 2026-10-04); it stays pinned, residual on WP-0h's human acceptance list.

N1, N2 and N7 (render routes; N7 = caller-chosen `?url=` receives the minted token) are owner WP-0i and pinned in-process in `tests/authz/test_render_routes.py`.

**Why:** INV-3 says authorisation decisions never change silently. A fix has to be a security-reviewed WP that flips these tests on purpose.

**How to apply:** When reviewing a WP that touches group or role APIs, `build_group`, `build_role`, the `/roles` map routes or `page_renderer`:
- If these tests fail, the fix is legitimate only if the WP records it and has a security verdict.
- If they still pass after a WP that claims to close an escalation, the fix did not work.
- A pin that asserts through the admin's view of a list can never fail (the admin sees every row); assert through the actor's own request.

Related: [[authz-suite-harness]]
