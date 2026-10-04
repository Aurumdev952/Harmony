---
name: authz-escalations-found
description: WP-2b pinned live privilege escalations (group_admin, group_moderator, role_administrator to admin); any WP touching groups/roles changes those tests deliberately
metadata:
  type: project
---

On 2026-10-04, WP-2b found three privilege escalations on main and pinned them in `tests/authz/http/test_escalation.py`, as current behaviour (INV-3):
- `group_admin` creates a group that carries the admin role.
- `group_moderator` patches its own group's roles.
- `role_administrator` creates a role with any permissions and is auto-added to it.

**Why:** INV-3 says authorisation decisions never change silently. A fix has to be a security-reviewed WP that flips these tests on purpose.

**How to apply:** When reviewing a WP that touches group or role APIs, `build_group`, `build_role` or `add_current_user_to_role`:
- If these tests fail, the fix is legitimate only if the WP records it and has a security verdict.
- If they still pass after a WP that claims to close an escalation, the fix did not work.

Related: [[authz-suite-harness]]
