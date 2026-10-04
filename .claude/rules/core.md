---
paths:
  - "harmony/core/**"
  - "config/**"
  - "data/query/**"
  - "db/**"
  - "models/**"
  - "util/**"
  - "web/server/query/**"
  - "web/server/data/**"
  - "web/server/migrations/**"
---

These files belong to the **core** role in the Harmony migration (`docs/modernisation/SPEC.md` section 6). Check ownership with `python3 scripts/agents/ownership.py who <path>`.

Before editing, load `harmony-query-engine`, `harmony-sqlalchemy-alembic`, `pydantic:pydantic` and `harmony-migration-protocol` with the Skill tool, unless they are already loaded.

Results (INV-2) and authorisation decisions (INV-3) must not change silently. Run `uv run pytest tests/golden tests/authz` after every unit. `harmony/core` imports no web framework.
