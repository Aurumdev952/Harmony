---
name: account-handover-guard
description: WP-0j rule for routes that can hand over an account (rename, password reset), decision 0010's hiding of administrators through a group, and traps for porting both to FastAPI (WP-5d)
metadata:
  type: project
---

Since WP-0j (2026-10-05/06, `mig/WP-0j-rename-reset-guard`, stacked on WP-0h):
- `UserResourceManager` hides users holding admin directly **or through a group** from every non-superuser *identity* (`SuperUserPermission().can()`, decision 0010). Every user item route and the list answer 404 for them. Narrowed admin tokens no longer see direct admins either.
- `grants.verify_may_rename` and `verify_may_reset_password` refuse a non-superuser identity unless the target's grants are among the caller's account's. That means roles by id (`held_role_ids()`), groups (`member_group_ids()`), and each user ACL's needs covered exactly or by the sitewide `ItemNeed(p, None, type)`.

**Why:**
- A rename plus a reset mails the reset link to an address the caller picked (H5).
- Round 1 skipped the hiding on the grounds that "the guard closes the takeover, hiding only turns 403 into 404". The reviewer showed that delete, force-delete, deactivate and demote still reached group admins. So the lead adopted the hiding.
- Lesson: when deciding not to hide something, check every route the hidden item reaches, not only the one under review.

**How to apply:**
- In WP-5d, put the same subset check on every account-handover route (`/password` and `/generate_api_token` too).
- In WP-5d, keep the admin hiding in the FastAPI user queries.
- WP-5d also owns the Low residuals: peers or higher non-admin users can be deleted, force-deleted, deactivated or demoted; force-delete destroys dashboards; a user can be removed from a group the caller is not in; self force-delete; no audit line for destructive operations.
- Breadth traps:
  - Dashboard authors hold a `dashboard_admin` owner ACL.
  - Alert ACLs yield `alert_definitions` needs that no seeded role covers sitewide, so alert authors need a superuser.
- Mutation-script trap: a helper named `/tmp/<dir>/log.py` next to the script shadowed the repo's `log` module when pytest ran from a copied tree. It even appended argv to the WP file. Never name temp scripts after repo top-level packages (`log`, `util`, `config`, `data`, `db`, `models`, `web`).

Related: [[narrowed-admin-tokens]]
