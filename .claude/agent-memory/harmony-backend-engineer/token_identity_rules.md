---
name: token-identity-rules
description: How Flask JWTs bind to accounts after WP-0k (user_id claim, API token row, iat vs created in the DB clock) and the traps found doing it
metadata:
  type: project
---

Since WP-0k (2026-10-05) a JWT signs in only the account it was issued to (`account_for_token` in `signal_handlers.py`):
- session and render tokens carry `user_claims.user_id`; `create_user_access_token` and `login_user` take a `User`, not a username (WP-0h/0j harness helpers had to change on merge);
- API tokens (`user_claims.id`) are checked against the `api_token` row on every request; there is no memo any more;
- pre-0k sessions get the one non-pending account equal to the identity ignoring case, else nobody;
- every token: account active, username exactly the identity, `created` not in a later second than `iat`.
- Fake users in other suites (SimpleNamespace) need `is_active=True` now that `authentication_required` checks it.
- Pre-0k sessions resolve by the OLD ILIKE pattern, unique among non-pending accounts (not by equality): typing `john_doe` signed in `john.doe`.
- Sign-in (`find_user_by_username`, active first) and target lookups (`find_named_account`, exact spelling any status) are different rules; never use the sign-in one where a caller names an account.
- Render tokens (WP-1h `render_token(account, …)`) are refused in `account_for_token` once spent; tests fake only `signal_handlers.active_account`.
- Test module basenames must be unique across tests/web (rootdir-less import): `tests/web/usernames/test_render_tokens.py` clashed with `tests/web/render/`.

**Why:** WP-2b T1/T2 showed deleted users' tokens signing in recreated usernames.

**How to apply:**
- `user.created` is a naive timestamp written by the database's `current_timestamp()`, so on Postgres it is in the session time zone, not UTC. Never compare it with a UTC epoch in Python; compare in SQL (`CAST(to_timestamp(iat) AS TIMESTAMP)`). A lead review caught the Python comparison as fail-open behind UTC.
- The FastAPI `PrincipalDep` must port all three rules (C-5 section of WP-0k.md).
- A throwaway Postgres for a test: `docker run -d --rm -p 127.0.0.1::5432` with the digest from `docker-compose.db.yaml`, `ALTER DATABASE ... SET timezone` per database; mark the test `stack` so CI's unit job deselects it.
- The worktree-isolation guard refuses long Bash heredocs that mention merges or other worktrees' paths; edit WP files with the Edit tool and run git in short separate commands.

Related: [[ruff-format-py38-trap]]
