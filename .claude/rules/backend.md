---
paths:
  - "harmony/api/**"
  - "harmony/worker/**"
  - "web/server/**"
  - "web/python_client/**"
  - "graphql/**"
---

These files belong to the **backend** role in the Harmony migration (`docs/modernisation/SPEC.md` section 6). Check ownership with `python3 scripts/agents/ownership.py who <path>`.

Before editing, load `harmony-fastapi`, `fastapi`, `harmony-celery` and `harmony-migration-protocol` with the Skill tool, unless they are already loaded.

New routes go under `/api/v3` in `harmony/api`. Each domain move deletes its Potion resource in the same stack and replays `tests/contract/`. Stored `$ref` URIs stay readable until WP-5g.
