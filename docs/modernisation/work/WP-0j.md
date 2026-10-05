---
wp: "0j"
title: "Refuse username changes and password resets that reach a higher-privileged account"
status: building
owner_role: "backend"
instances:
  - name: "backend-0j"
    files:
      - "web/server/api/user_api_models.py"
      - "web/server/security/grants.py"
      - "tests/web/privilege_escalation/test_rename_and_reset.py"
      - "docs/modernisation/work/WP-0j.md"
branch: "mig/WP-0j-rename-reset-guard"
requirements: [INV-3, QA-1, QA-4]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0j: Refuse username changes and password resets that reach a higher-privileged account

Phase detail: phase-0-security-and-subtraction.md, section 0j (on `mig/integration`). Added by decision 0005 (`decisions/0005-wp-0j-account-takeover-via-rename-and-reset.md`, on `mig/integration`) after the WP-0h security round 2 confirmed H5 live. Depends on WP-0h: this branch starts from `mig/WP-0h-privilege-escalations` at `a615058` and reuses its harness (`tests/web/privilege_escalation`) and `web/server/security/grants.py`.

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Claim; read decision 0005, phase 0j, the user Potion resource, `send_reset_password` and the WP-0h grant helpers. Check: this file.
2. Failing tests on the WP-0h harness (`tests/web/privilege_escalation/test_rename_and_reset.py`): `manager` + `user_admin` renaming, and resetting the password of, an admin-through-group user, plus the other grants a target can hold beyond the caller (a role, a group, an ACL, a query-policy role, an exporting role); equal-or-lesser targets still rename and reset; superusers unchanged; the mailer is a stub. Check: the refusal tests fail on this branch's base (`a615058`) for the reason H5 gives (200/204, username changed, mail handed to the stub); the unchanged-behaviour tests pass there.
3. The guard in `grants.py`, called from `PATCH /api2/user/<id>` (only when `username` changes) and `POST /api2/user/<id>/reset_password`. Check: the new tests pass, the WP-0h tests still pass; pylint (CI errors) and black 22.6.0 clean on the changed files.
4. Decide the optional `UserResourceManager` change with a note for security; INV-3 table; human acceptance item; Request to qa for the WP-2b pins. Check: this file.
5. `pstack:interrogate` on the guard; triage findings. Then `status: review`.
