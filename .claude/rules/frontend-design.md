---
paths:
  - "web/client/design/**"
  - "web/client/components/**"
  - "web/public/scss/**"
  - "web/public/fonts/**"
---

These files belong to the **frontend-design** role in the Harmony migration (`docs/modernisation/SPEC.md` section 6). Check ownership with `python3 scripts/agents/ownership.py who <path>`.

Before editing, load `frontend-design:frontend-design`, `harmony-design-system`, `heroui-react` and `harmony-migration-protocol` with the Skill tool, unless they are already loaded.

Invoke `/frontend-design:frontend-design` before any visual change. HeroUI v3 only (compound components, `onPress`, no provider). Tokens only: no hex literals outside `web/client/design/tokens.css`. Numbers use `--font-numeric`.
