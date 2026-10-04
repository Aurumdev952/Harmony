---
paths:
  - "tests/**"
  - "e2e/**"
  - "scripts/perf/**"
---

These files belong to the **qa** role in the Harmony migration (`docs/modernisation/SPEC.md` section 6). Check ownership with `python3 scripts/agents/ownership.py who <path>`.

Before editing, load `harmony-qa` and `harmony-migration-protocol` with the Skill tool, unless they are already loaded.

Never weaken a test to make it pass. Never normalise numbers out of golden comparisons.
