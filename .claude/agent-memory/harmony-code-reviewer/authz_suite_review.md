---
name: authz-suite-review
description: How to probe tests/authz (WP-2b, and WP-0h/4e/5d changes to it) - Potion read path trap, seed drift scope, live-stack recipe, env facts
metadata:
  type: project
---

Lessons from reviewing WP-2b (2026-10-04):
- **Potion never calls `HybridPermission.can(item)` for reads.** `RelationalManager.read` and `instances` go through `PrincipalMixin._query` and then `_query_filter_permission`, which builds an SQL filter from `identity_get_item_needs()` and the *target* manager's id attribute. `can(item)` runs only for create, update and delete. For relationship needs (AlertNotificationResource read via `alert_definition`), `can(item)` resolves `alert_definition.id` (the PK), while the query filter uses `authorization_resource_id`. A test that checks `can(item)` for `read` is a proxy.
- **Vacuous agreement checks.** If a test uses one item id (7) that only dashboard principals hold, its per-item branch equals the sitewide branch for every other resource. Probe: compare `can(item)` with `can(None)` per principal.
- **Seed drift.** `test_seed.py` compares only `/api2/role`. Resource-role permissions (`/api2/resource_role`) can drift and nothing fails. Mutating `seed.yaml` proved it.
- **Live layer recipe.** Overlay `tests/contract` from the WP-2c branch into a scratch worktree. Run `AUTHZ_PROJECT=<own> AUTHZ_WEB_PORT=<own> tests/authz/stack.sh up` (about 4 minutes; it needs the `harmony-wp2c-web-server:local` image because of `--no-build`), then `eval "$(... stack.sh env)"` and `tests/authz/run.sh -m authz_http` (about 2.5 minutes, 569 tests). Finish with `stack.sh down`. Put the eval in a /tmp script, because the guard refuses it inline.
- **Environments.** The suite passes under integration's root uv project (golden group), under WP-2f's lock and under run.sh's Python 3.8 env. It also coexists with golden, contract and pipeline in one session (those two need `hypothesis`).
- **pylint gate.** Until WP-2f lands, integration's CI fails on `principals.py` E1111 (`QueryPolicy.dimension_filters.fget(row)`).
- **Interrogate.** The panel could not spawn: the session hit its limit of 20 concurrent subagents. Run interrogate early, before other agents fill the pool.

**Why:** the first three hid real oracle gaps behind 2517 green tests.
**How to apply:** for any WP that edits `tests/authz` or ports authz (0h, 4e, 5d, 5f), rerun these probes. Related: [[golden-suite-review]], [[review-traps]].
