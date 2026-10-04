---
paths:
  - "web/client/**"
  - "vite.config.ts"
  - "tsconfig*.json"
  - "eslint.config.js"
  - "package.json"
  - "web/public/js/**"
---

These files belong to the **frontend-platform** role in the Harmony migration (`docs/modernisation/SPEC.md` section 6). Check ownership with `python3 scripts/agents/ownership.py who <path>`.

Before editing, load `harmony-frontend` and `harmony-migration-protocol` with the Skill tool, unless they are already loaded.

No new Flow, decorators, jQuery, bluebird or moment. Components under `web/client/components/**` belong to frontend-design, and visualizations to visualization.
