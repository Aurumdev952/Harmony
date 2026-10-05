---
wp: "0l"
title: "Match resource, role, group and user names exactly, never as patterns"
status: building
owner_role: "backend"
instances:
  - name: "backend-0l"
    files:
      - "web/server/routes/views/core.py"
      - "web/server/routes/views/resource.py"
      - "web/server/routes/views/users.py"
      - "web/server/routes/views/groups.py"
      - "web/server/routes/views/dashboard.py"
      - "web/server/routes/views/alerts.py"
      - "web/server/database/alerts.py"
      - "web/server/security/grants.py"
      - "web/server/api/user_api_models.py"
      - "web/server/api/group_api_models.py"
      - "tests/privilege_escalation/conftest.py"
      - "tests/privilege_escalation/test_named_lookups.py"
      - "docs/modernisation/work/WP-0l.md"
  - name: "core-0l"
    files:
      - "web/server/data/data_access.py"
  - name: "qa-0l-tests"
    files: []
branch: "mig/WP-0l-exact-name-matching"
requirements: [INV-3, QA-1, QA-4]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0l: Match resource, role, group and user names exactly, never as patterns

Phase detail: [phase-0-security-and-subtraction.md, section 0l](../phase-0-security-and-subtraction.md). Added by [decision 0012](../decisions/0012-wp-0l-exact-resource-and-principal-name-matching.md). Depends on 0k.

## Plan

Units, in order. Each line names the change and the check that ends it. Every unit starts with a test that fails on `mig/integration` 7c34bca.

1. `find_one_by_fields(..., case_sensitive=False)` compares `func.lower(field) == func.lower(value)` instead of `field.ilike(value)`. The file is core's: requested below; core works it on `mig/WP-0l-exact-name-matching-core`, merged here when it lands. Check: a lookup of `a_b` never returns `axb`; `ABC` still finds `abc`.
2. Sharing (`update_user_resource_roles`, `update_group_resource_roles`, share removal in `_update_group_roles`) and the author grants on dashboard and alert creation use the resource object they were given; nothing re-finds a resource by its own name. Share removal acts on the exact principal. Check: `POST /api2/resource/<a_b>/roles` stores ACLs on `a_b` only, with `axb` created first; the creator of `a_b` becomes admin of `a_b`, not `axb`.
3. 403 bodies from `verify_acl_grants`, and the 404 type-mismatch body from `try_get_role_and_resource`, do not repeat resource names. Check: bodies carry no resource name; the audit line still does.
4. `try_get_user` and its callers (group membership, role membership, `lookup_author`, alert ownership transfer) match exactly, ignoring case. Check: adding `john_doe@…` to a group or role never adds `john.doe@…`; `John_Doe@…` still finds `john_doe@…`.
5. Tests for the three tracing notes: `get_resource_by_type_and_name` combining conditions with Python `and`; the legacy `POST /api2/{user,group}/<id>/roles` building `UserRoles`/`GroupRoles` with a `resource_id`; `PATCH /roles` with an empty body. Wrong-row and 500 outcomes are fixed here; the rest recorded below.
6. INV-3 table with the decision 0012 rows, and a live before/after on one stack.
7. Full checks: `tests/web`, `tests/privilege_escalation`, the `tests/authz` pure layer, lint, mypy, `ci/check_py38_syntax.py` on CPython 3.8.20, `ci/pytest_suites.sh`, `task_gate.py WP-0l`. Then `status: review`.

## Contract changes

None.

## Requests

- [ ] core: in `web/server/data/data_access.py` `find_one_by_fields`, replace `query.filter(field.ilike(field_value))` with `query.filter(func.lower(field) == func.lower(field_value))` for string values when `case_sensitive=False` (blocks unit 1; the lead has dispatched core on `mig/WP-0l-exact-name-matching-core`, to be merged here).

## Log

One line per finished unit: `YYYY-MM-DD <instance> unit N: <what>; check: <command and result>`

## Evidence

Links to test output, screenshots, perf samples and `verify` reports.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
