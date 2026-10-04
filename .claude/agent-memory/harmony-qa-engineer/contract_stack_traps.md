---
name: contract-stack-traps
description: Traps when running Harmony's Flask app locally for tests (WP-2c contract stack) - Druid at import time, bcrypt, mail egress, worktree command guard
metadata:
  type: project
---

Running the Flask app outside production needs more than Postgres (learned 2026-10-04 building `tests/contract/stack/`):

- `flask db upgrade` needs Druid: `config/<code>/database.py` queries Druid at import and seed migration `93bb8d693499` asks Druid for dimension values. A stdlib stub answering `/druid/coordinator/v1/metadata/datasources` with `["harmony_demo_20240101"]` and `[]` for queries is enough. `DRUID_HOST` must be scheme+host with no port (the code appends `:8081`/`:8082`).
- `ZEN_OFFLINE=1` swaps in a random mock query client: viz shapes are stable, values random; `/api2/query/hierarchy` 500s (no TOTAL row) under the mock.
- Routes only register when `SERVER_SOFTWARE` starts with `gunicorn`; run `web/gunicorn_server.py`, not `create_app()` directly.
- bcrypt is unpinned on main; bcrypt 5 + passlib 1.7.4 breaks every hash/verify ("password cannot be longer than 72 bytes"). The stack pins `bcrypt==4.0.1` in a derived image until WP-0b's requirements pin lands.
- `PATCH /api2/{user,group}/<id>/roles` deletes the Role rows the holder has (not the membership): never point it at a seeded role in a case, or the role vanishes for everyone (WP-0h scope).
- A thumbnail miss on `/api2/storage/retrieve` leaves a PENDING marker for 10 minutes and later reads sleep on it; seed the cache instead (`stack/seed_cache.py`).
- `monkeypatch.delenv(name, raising=False)` on an unset variable records nothing, so a value the code exports leaks into later tests; `setenv` first.
- Email defaults to `smtp.mailgun.org`; set `EMAIL_HOST` to a mailpit sink or every dashboard create stalls ~5 s and tries egress.
- Login for scripts: `POST /api2/authentication/login?set_cookie=true` JSON `{email,password}`; no CSRF.

**Why:** each of these cost a stack restart to discover.
**How to apply:** reuse `tests/contract/stack/` (compose + `stack.sh`) for any QA work that needs a live Flask app; see [[worktree-command-guard]].
