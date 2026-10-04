---
wp: "2b"
title: "Permission and policy suite"
status: claimed
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

1. (planning)

## Contract changes

None. The suite is written against today's Flask path and later re-pointed at `harmony.core.authz.can()` (C-2), which must agree case for case.

## Requests

## Log

## Evidence

## Findings for security

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
