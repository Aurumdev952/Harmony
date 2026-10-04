---
wp: "0h"
title: "Close privilege escalations in group and role management"
status: claimed
owner_role: "backend"
instances:
  - name: "backend-6"
    files:
      - "web/server/api/**"
      - "web/server/security/**"
      - "web/server/potion/**"
      - "tests/web/privilege_escalation/**"
      - "docs/modernisation/work/WP-0h.md"
branch: "mig/WP-0h-privilege-escalations"
requirements: [INV-3]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0h: Close privilege escalations in group and role management

Phase detail: [phase-0-security-and-subtraction.md, section 0h](../phase-0-security-and-subtraction.md). Added by [decision 0003](../decisions/0003-wp-0h-privilege-escalations.md).

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Read the group and role Potion resources, their managers, and the permission plumbing (`pstack:how`). Check: notes in this file name the code paths behind each escalation.
2. Failing tests, one per escalation, through the real Flask app and Potion routes with constructed users. Check: the three tests fail on the integration branch for the reason the escalation gives.
3. The fix. Check: the three tests pass; existing tests for the touched area pass.
4. INV-3 difference table, plus the WP-2b pure layer run against the fix. Check: suite output recorded under Evidence.
5. `pstack:interrogate` on the fix, findings addressed, `status: review`.

## Contract changes

None.

## Requests

## Log

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
