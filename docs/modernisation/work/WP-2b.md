---
wp: "2b"
title: "Permission and policy suite"
status: building
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

The suite records what the Flask path decides today. Later it is pointed at `harmony.core.authz.can()` (C-2), which must agree case for case. It has two layers:
- **Pure.** No server, database or Druid. Identities come from the production need-building code (`BaseUserMixin.enumerate_permissions`, then `signal_handlers.on_identity_loaded`, including JWT narrowing). Only the rows that code reads are replaced: roles, groups, ACLs, the configuration store and JWT claims.
- **Live stack.** Marked `authz_http`, skipped unless `AUTHZ_BASE_URL` is set. Covers what only HTTP can reach: Potion list filtering, manager filters, decorator status codes, and seed drift.

1. Principal builder plus the `is_authorized` decision table: every seeded role and the special principals (anonymous, public, ACL holders, group members, browser sessions, render tokens) against every check the app makes. Check: `tests/authz/run.sh`.
2. Query-policy filter table: `_construct_authorization_filter` and `restrict_query_filter_to_user_permissions` over harmony_demo plus synthetic hierarchical configs, and `AuthorizedQueryClient.run_query` for non-superusers, superusers and public users (WP-0c request). `run_raw_query` is deliberately not tested while WP-0c decides it. Check: `tests/authz/run.sh`.
3. Need algebra and token narrowing: `QueryNeed` and `DimensionFilter` containment and intersection, `QueryPermission.allows`, `_compute_token_item_needs` and `_compute_token_query_needs`. Check: `tests/authz/run.sh`.
4. Potion permission wiring: the effective needs `ZenysisPrincipalMixin` gives each Potion resource for read, create, update and delete. Check: `tests/authz/run.sh`.
5. Live-stack layer (`tests/authz/http/`): seed drift, per-role users provisioned through the admin API, page and API status codes, Potion list filtering, and the admin self-delete guard. Check: `tests/authz/run.sh -m authz_http` against `tests/authz/stack.sh up`.
6. Findings for security, evidence, `status: review`.

### How to run

```bash
tests/authz/run.sh                     # pure layer: uv, Python 3.8, the pinned web requirements
tests/authz/stack.sh up                # private copy of the WP-2c stack (project harmony-wp2b-authz, port 58660)
eval "$(tests/authz/stack.sh env)"
tests/authz/run.sh -m authz_http       # live-stack layer
tests/authz/stack.sh down
```

`run.sh` rewrites the `-e git+...` lines in `requirements*.txt` into direct references, because `uv run --with-requirements` rejects editable lines, then runs `uv run --no-project -p 3.8 --with-requirements <rewritten> --with 'pytest<8' --with pyyaml --with requests python -m pytest tests/authz`. The web stack pins Python 3.8, so this does not use Python 3.13. `stack.sh` needs `tests/contract/stack/` from WP-2c.

## Contract changes

None. The suite is written against today's Flask path and later re-pointed at `harmony.core.authz.can()` (C-2), which must agree case for case.

## Requests

## Log

- 2026-10-04 qa-3 unit 1: principal builder (`principals.py`, `principals.yaml`, `seed.yaml` captured from a freshly migrated harmony_demo DB) and the `is_authorized` table (`decisions.yaml`: 56 checks x 41 principals). Check: `tests/authz/run.sh` gives 2338 passed. Mutation check: dropping `role:manager` from `view_admin_page` and narrowing `view_resource user` to superusers gave 39 failures, one per changed row.

## Evidence

## Findings for security

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
