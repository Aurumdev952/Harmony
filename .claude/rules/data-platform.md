---
paths:
  - "druid_setup/**"
  - "db/druid/**"
  - "scripts/druid/**"
---

These files belong to the **data-platform (indexing) and core (query builder)** role in the Harmony migration (`docs/modernisation/SPEC.md` section 6). Check ownership with `python3 scripts/agents/ownership.py who <path>`.

Before editing, load `harmony-druid` and `harmony-migration-protocol` with the Skill tool, unless they are already loaded.

Confirm every Druid version fact against the target release notes. Null semantics changed in Druid 28 and 32. JavaScript must end up disabled.
