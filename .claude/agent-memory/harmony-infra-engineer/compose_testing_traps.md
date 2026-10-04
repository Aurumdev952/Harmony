---
name: compose-testing-traps
description: How to test Harmony's Compose files safely in a worktree agent - env files, hooks, throwaway stacks, anonymous volumes, redis-cli exit codes
metadata:
  type: feedback
---

Lessons from WP-0b (2026-10-04) for checking Compose files without touching `.env` or leaving debris.

- **Never let Compose read the repo `.env`.** Always pass `--env-file <tmp file with dummy values>`. `tests/infra/test_compose.py` does this (`render()`/`config()` helpers); reuse it for new Compose assertions.
- **`.env.example` is unreadable to agents** (settings deny `.env*`), even though infra owns it. Route edits to it through the lead/human. `grep -r` still reads it, so always add `--exclude='.env*'` to repo-wide greps.
- **Confirm a variable has a reader before fixing its syntax.** WP-0b first corrected `POSTGRES_DB_URI:=` and then had to delete it, because nothing read it. Grep for the name across the code first.
- **Worktree Bash guard** rejects compound commands that mention `git`/`github` URLs, `export`, `sh -c "$VAR"`, or long `&&` chains mixing sed with `${...:?}`. Split into plain single commands; use the Edit tool for YAML containing `${VAR:?msg}`.
- **zsh does not word-split `$var`**, so `for o in "-f a.yaml"; do docker compose $o` passes one argument. Loop over file names instead.
- **Host ports 5432 and 6379 are taken** by host services on the dev machine. For runtime checks, use a throwaway project (`-p wp<id>-check`) plus a /tmp overlay with `ports: !override [...]`.
- **`volumes: !reset []` does not avoid volumes.** postgres and redis declare `VOLUME`, so Docker creates anonymous volumes that `down` (without `-v`) leaves behind, and they cannot be told apart from other agents' volumes afterwards. Use `tmpfs: [/var/lib/postgresql/data]` / `tmpfs: [/data]` in the overlay instead.
- **`redis-cli` exits 0 on NOAUTH/WRONGPASS.** Healthchecks must match the reply (`redis-cli ping | grep -qx PONG`). Use `REDISCLI_AUTH` env for the password.
- Repo Python style is black with `--skip-string-normalization`. Check with `uvx ruff format --check --config "format.quote-style='single'"` until WP-2f adds ruff config.

**Why:** each of these cost a retry or left something to clean up in WP-0b.
**How to apply:** any infra unit that renders or starts Compose services.
