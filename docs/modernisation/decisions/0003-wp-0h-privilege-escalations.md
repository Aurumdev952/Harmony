# 0003. Add WP-0h: close the privilege escalations WP-2b found

Status: applied by the lead on 2026-10-04, pending human ratification (SPEC section 10).

## Context

While recording today's authorisation decisions, WP-2b (qa-3) reproduced three escalations to site administrator on a fresh `harmony_demo` stack, each pinned in `tests/authz/http/test_escalation.py`:

1. A user with only `group_admin` creates a group that names the admin role (`POST /api2/group` with `roles: ["/api2/role/1"]`); the creator is added to the group and becomes site admin. `build_group` resolves role URIs with `Transaction.find_by_id`, bypassing the `RoleResourceManager` filter.
2. A `group_moderator` of any group patches that group's roles to include admin (`PATCH /api2/group/<id>`); sitewide `edit_resource` on group is enough.
3. A `role_administrator` creates a role with arbitrary permissions or resource roles (`POST /api2/role`); the creator is auto-added and gains, for example, `view_admin_page` and `dashboard_admin` sitewide, bypassing the `update_permissions` gate.

Phase 0's goal is to close open exposures. No WP in SPEC section 5 covers these, and WP-0c is already large.

## Decision

Add **WP-0h: Close privilege escalations in group and role management** to SPEC section 5: owner `backend`, supporting `core, security, qa`, depends on `2b` (for the pinned cases), Sec `yes`. Detail added to phase 0 as section 0h.

Rules for WP-0h:
- Every change to an authorisation outcome is listed in the WP file as an INV-3 difference table (who could do what before, who can after) and accepted by the security reviewer and the human before merge.
- The WP-2b escalation tests are flipped from "pinned today" to "expected refusal" in the same stack of commits, by qa, so the suite never passes with the escalation open.

## Consequences

- SPEC 1.3 adds the WP row; phase-0 adds section 0h.
- WP-0h starts as soon as WP-2b's escalation cases are on its branch; it merges after WP-2b.
