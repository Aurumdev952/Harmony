---
name: backend-testing-traps
description: Traps when testing Flask backend changes in Harmony worktrees (real Postgres fixture, contract stack, worktree guard, formatting)
metadata:
  type: feedback
---

- **Real-Postgres tests.** `tests/throwaway_postgres.py` (from WP-2c) gives `postgres_database`: a fresh database on the stack's pinned postgres image, or on `HARMONY_TEST_POSTGRES_URL`. Re-export its fixtures from a conftest.
  - **Why:** the uv env has no Flask app factory (`flask_migrate`, `zen_config` are missing), so route modules cannot be imported bare.
  - **How to apply:** put route logic in a `web/server/routes/views/*` helper and test that helper. Prove the route wiring with a live check on the contract stack.
- **Mappers.** A test touching `User` must import every `models.alchemy.*` subpackage first, or mapper configuration fails on `query_policy_role`. `User.status` is view-only, so commit the `UserStatus` row before inserting the user.
- **Contract stack.** Do not PATCH the stack admin's own user in a live check. A PATCH with `roles` or `groups` set to `[]` strips its admin rights, and every later call returns 401. Create a throwaway user for the check, then recreate the stack before replay.
- **Worktree guard.** The isolated-worktree guard refuses `source`, `eval "$(...)"` and compound heredoc-plus-command lines. Write `stack.sh env` to a file and pass the literal values as env prefixes. Edit `/tmp` scripts with the Edit tool.
- **Formatting.**
  - `tests/web` uses single quotes; format it with `ruff format --config "format.quote-style='single'"`.
  - `tests/contract` and `tests/db` use ruff's double-quote default.
  - Never `ruff format` an existing file wholesale; it rewrites every quote.
- **Ownership.** `db/postgres/utils.py` and `models/**` belong to core, even when a backend route is the only caller. Hand core a patch you have verified by loading it through a pytest plugin (`exec` the proposed file into the module namespace), with no edit to the repo.
