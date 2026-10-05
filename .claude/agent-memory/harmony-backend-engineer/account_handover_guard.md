---
name: account-handover-guard
description: WP-0j rule for routes that can hand over an account (rename, password reset) and how to judge "target holds no more than caller"; traps for porting it to FastAPI (WP-5d)
metadata:
  type: project
---

Since WP-0j (2026-10-05, `mig/WP-0j-rename-reset-guard`, stacked on WP-0h), `grants.verify_may_rename` and `verify_may_reset_password` refuse a non-superuser identity unless the target's grants are among the caller's account's:
- roles by id, direct or through a group, with admin never held;
- group ids;
- each user ACL's needs covered exactly or by the sitewide `ItemNeed(p, None, type)`, the cover `augment_needs` gives `is_authorized`.

Policies and export come only from roles. Group ACLs come with membership.

**Why:** a rename plus a reset mails the reset link to an address the caller picked (H5). Comparing roles by id rather than by needs is deliberate (decision 0005). Role identity decides which role item routes an account reaches.

**How to apply:**
- In WP-5d, put the same check on every account-handover route: username change, reset, and also `/password` and `/generate_api_token`, which today rely on `change_password` being superuser-only.
- The breadth is real: dashboard authors hold a `dashboard_admin` owner ACL, so non-superuser user editors cannot reset them.
- `UserResourceManager` hiding admins through a group was not adopted. It is left for WP-5d's user list.
- Trap: `pstack:interrogate` can fail to spawn when the session hits 20 concurrent subagents. The prompt is reusable from a file.

Related: [[narrowed-admin-tokens]]
