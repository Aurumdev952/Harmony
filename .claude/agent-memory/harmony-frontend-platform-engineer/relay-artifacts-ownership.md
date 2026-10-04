---
name: relay-artifacts-ownership
description: Relay __generated__ artifacts under web/client/components belong to frontend-design, not frontend-platform; how to verify a regeneration without committing it
metadata:
  type: project
---

Generated Relay artifacts in `web/client/components/**/__generated__/` are owned by frontend-design (SPEC section 6: the more specific `web/client/components/**` glob wins over `web/client/**`). Running `relay-compiler` from Bash writes into those paths without passing the ownership hook.

**Why:** on 2026-10-04 the lead asked frontend-platform-2 to commit a WP-0a Relay regeneration. The six changed files were all frontend-design paths, so committing them would have bypassed the hook.

**How to apply:** run `uv run python scripts/agents/ownership.py who <path>` on the compiler's `Updated:` list before committing. If the files are not yours, verify the run (only Flow type lines above `const node` change, `flow check` unchanged), restore the files and hand the owner the exact command. The compiler is deterministic, so no patch is needed. `yarn relay` runs in watch mode; run `./node_modules/.bin/relay-compiler` once instead. Related: [[local-yarn-build]]
