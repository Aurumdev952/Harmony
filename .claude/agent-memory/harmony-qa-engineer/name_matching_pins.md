---
name: name-matching-pins
description: WP-0l ILIKE name-matching pins: row-order trick, where the in-process harness lives, live setup traps, contract re-record via a /tmp wrapper
metadata:
  type: project
---

WP-0l (decision 0012, 2026-10-06) pins live in `tests/privilege_escalation/test_exact_name_matching.py`, `tests/web/test_exact_name_lookup.py` and `tests/authz/http/test_name_matching.py`.

- **Row order decides the wrong row.** `ILIKE ... .first()` with no ORDER BY returned the row stored earlier on every one of 5 fresh Postgres runs. Store the look-alike first to see the bug, and also run the named-first order, which passes before and after (proves order-dependence).
- **An UPDATE moves a row after later inserts** (new ctid). A dashboard PATCH writes the resource label from the title *before* the save, so only the second retitle rewrites the resource row. Probe ctid with `docker exec <project>-postgres-1 psql ... -tAc "select ctid,..."`.
- **Live setup must avoid the bug it pins:** set users' ACLs and groups through `PATCH /api2/user/<id>` (groups by URI, ACLs by resource name with no look-alike), never through `/users` or `/roles` by username.
- **Full Potion app harness = tests/privilege_escalation** (own process). tests/web is one process and tests/web/render already binds Potion resources, so a second full app there collides.
- In-process dashboard create/share needs `url_for` patched in `dashboard_api_models` and `permission_api_models`, plus fake `email_renderer`/`notification_service` on the app.
- The guard refuses `record --only '*.x'` (glob text); run the recorder from a /tmp Python wrapper with subprocess.
- `storage.retrieve.unknown_slug` recording says 500 but the code serves 404 since WP-0i; it was left stale on integration (reported, not re-recorded in WP-0l).

Related: [[authz-suite-harness]], [[worktree-guard-bash]], [[reference-contract-stack]]
