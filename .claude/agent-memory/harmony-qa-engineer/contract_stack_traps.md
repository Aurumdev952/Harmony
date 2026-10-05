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

Added 2026-10-04 (round 3):
- Before core's F13 fix (merged into WP-2c 2026-10-05) `POST /api/import_self_serve` ran `TRUNCATE ... CASCADE` and wiped unpublished-field mappings, dimension metadata and `source_config`. With the fix the seeded mappings survive the import; a branch without it records those lists empty.
- `ci/lint_python.sh` runs full `ruff check` on every file the branch changes, including tests merged in from other roles' branches; run `ruff check` on the whole merged diff, not only `tests/contract` (an f-string `SELECT` in `tests/db` tripped S608).
- Relay cases must send the variables the client builds, not the raw UI state: the unpublished-field table sends `searchText` as `%<text>%` (`%%` when empty); `""` matches nothing.
- If the lead tells you to work in another agent's worktree and the guard refuses, switch your own worktree to the WP branch (once the other is detached) and rsync the uncommitted files across; plain file reads of the other worktree are allowed, git there is not.

Added 2026-10-05 (WP-2c final round):
- Once any conftest imports `tests.<module>`, `tests` becomes a namespace package and Flask 1.x cannot find an instance path for `Flask('tests.web')`: pass both `root_path` and `instance_path`. Run the full `ci/pytest_suites.sh` after merging other roles' test helpers, not only the suites you own.
- `security_review` must follow the merged diff, not the WP's starting row: a supporting fix that changes an allow/deny result (F12 token 401 to 200) needs a security verdict.
