---
paths:
  - "pipeline/**"
  - "data/pipeline/**"
  - "data/alerts/**"
  - "util/pipeline/**"
  - "harmony/pipeline/**"
---

These files belong to the **pipeline** role in the Harmony migration (`docs/modernisation/SPEC.md` section 6). Check ownership with `python3 scripts/agents/ownership.py who <path>`.

Before editing, load `harmony-pipeline`, `polars:polars`, `dagster:dagster-expert` and `harmony-migration-protocol` with the Skill tool, unless they are already loaded.

The fixture suite (`tests/pipeline`) must produce identical rows before and after each change. Use lazy Polars with one sink. Failures stop and alert; nothing uses `|| true`.
