---
paths:
  - "web/client/components/visualizations/**"
  - "web/client/components/ui/visualizations/**"
  - "web/client/components/QueryResult/**"
---

These files belong to the **visualization** role in the Harmony migration (`docs/modernisation/SPEC.md` section 6). Check ownership with `python3 scripts/agents/ownership.py who <path>`.

Before editing, load `harmony-visualization`, `dataviz`, `maplibre-v6-migration` and `harmony-migration-protocol` with the Skill tool, unless they are already loaded.

Add a golden visual test before replacing any renderer. Chart fonts and colours come from tokens. Maps use MapLibre 6 with no default import.
