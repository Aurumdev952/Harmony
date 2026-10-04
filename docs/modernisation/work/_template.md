---
wp: "<id>"                # e.g. 1b
title: "<title from SPEC section 5>"
status: claimed           # claimed | planning | building | review | changes-requested | ready | blocked | done
owner_role: "<role>"      # core | backend | frontend-platform | frontend-design | visualization | data-platform | pipeline | infra | qa
instances:                # one entry per agent instance working this WP
  - name: "<role>-1"
    files: []             # paths or globs this instance has claimed; no overlap between instances
branch: "mig/WP-<id>-<slug>"
requirements: []          # e.g. [PERF-1, SEC-4]
contracts_consumed: []    # e.g. [C-3]
contracts_changed: []
security_review: false    # true when SPEC marks the WP Sec
---

# WP-<id>: <title>

## Plan

Units, in order. Each line names the change and the check that ends it.

1.

## Contract changes

Old shape, new shape, consumers, migration. Every consumer acknowledges below before merge.

## Requests

Changes needed from other roles: `- [ ] <role>: <request> (blocks unit N)`

## Log

One line per finished unit: `YYYY-MM-DD <instance> unit N: <what>; check: <command and result>`

## Evidence

Links to test output, screenshots, perf samples and `verify` reports.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
