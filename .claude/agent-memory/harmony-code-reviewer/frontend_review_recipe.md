---
name: frontend-review-recipe
description: How to reproduce frontend WP evidence (yarn lockfile, webpack bundles, CSS rule diff, Flow, Jinja render) in scratch worktrees, and the completion-gate trap for WPs that merge other roles' side branches
metadata:
  type: reference
---

Learned reviewing WP-0e on 2026-10-04.

**Gate trap: side-branch work from other roles.** `task_gate.py` runs the ownership check with the owner plus the *Supporting* column of the WP's SPEC section 5 row, not the WP file. If a WP merges `-backend`/`-design` side branches but the SPEC row says `none`, the gate refuses completion even when the lead approved the work. To simulate it, run this from an integration scratch worktree: `uv run --no-project python scripts/agents/ownership.py check --role <owner> [--role <supporting> ...] --head <branch>`. The fix is a lead edit to the SPEC row plus per-instance `files:` in the WP front matter (SPEC 7.2).

**Reproducing frontend evidence:**
- Base: use `mig/integration` once `git diff --stat <merge-base> mig/integration -- web package.json yarn.lock` is empty.
- Install: `NODE_OPTIONS=--dns-result-order=ipv4first yarn install --frozen-lockfile --ignore-scripts --prefer-offline`, about 55 s with a warm `~/.cache/yarn`.
- Build: `yarn build`, 30 to 50 s. Then `diff -rq web/public/build/min` across the two worktrees.
- Absolute bundle sizes differ between host Node 24 and the node:18.17 image. Compare base with head, not with the WP's numbers.
- Flow: call `node_modules/flow-bin/flow-linux64-v0.144.0/flow check <dir>` directly. Strip the worktree prefix, then diff the full output.
- CSS: parse the CSS with `node_modules/postcss` into one line per rule (see the frontend-design memory). The Write tool is needed for the script.
- Jinja: `uv run --no-project --with jinja2 python <script>`, with `ChainableUndefined` and `install_null_translations()`. `auth/layout.html` renders standalone, while `auth/user_profile.html` needs flask_user macros. Deleting the first lines of an included partial shifts the indentation of the next line, so use `diff -w`.

**Traps:**
- The guard refuses `cd /tmp/x && <compound>`. Run one simple command per call with absolute paths.
- The built-in `code-review` fork reads the live branch tip, which can be ahead of the assigned SHA (for example a QA verdict commit). It also flags lead-authorised merges as breaking CLAUDE.md "never merge". That is a false positive, because decision 0001 requires builders to merge decision branches.

Related: [[review-traps]], [[ci-review-facts]]
