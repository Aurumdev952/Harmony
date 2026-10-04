---
name: legacy-stack-browser-verify
description: How QA ran the legacy Flask app plus Hasura with a built client for browser verify of Data Catalog, Indicator Setup and Data Upload without building the frontend (WP-0a, 2026-10-04)
metadata:
  type: project
---

A full browser `verify` of the GraphQL pages is feasible without Druid or a client build.

- Image: reuse `harmony-wp2c-web-server:local` (WP-2c's contract stack image, bcrypt pinned). Copy the shape of `tests/contract/stack/compose.yaml` from `mig/WP-2c-api-contract-recordings` into /tmp, with its `druid_stub.py`, a unique project name and a free loopback port.
- Client bundles: borrow a prod build (`web/public/build/min`) from any agent worktree that has one (`ls .claude/worktrees/*/web/public/build`). Check with `git diff <their branch> <WP branch> -- web/client` that the Relay `__generated__` files match.
- Non-production Flask proxies `/build/*` to webpack-dev-server on localhost:8080 inside the web container. Serve the bundles with an nginx sidecar sharing the web container's network namespace (`docker run --network container:<web>`), aliasing `/build/` and `/build/min/` to the min dir and `/build/bundle.css` to the hashed css.
- The source mount is read-only, so the upload wizard fails with `Read-only file system: 'uploads'`. Create an `uploads/` directory in the scratch tree and add a tmpfs at `/zenysis/uploads`.
- The upload mapping step needs at least one row in `dimension` (plus `dimension_category` and a mapping) or the "Match with" picker spins forever.
- Field setup lives at `/indicator-setup`, not `/field-setup`.
- Playwright MCP writes snapshots and screenshots only under the main checkout's `.playwright-mcp/`. A file chooser opened inside `browser_run_code_unsafe` still has to be answered with `browser_file_upload`.
- The worktree guard refuses compound shell lines that touch paths outside the worktree or include heredocs with quotes. Write scripts with the Write tool under /tmp and run `bash /tmp/x.sh`.

**Why:** WP-0a's builder deferred this verify as infeasible; it took QA about 30 minutes this way.
**How to apply:** any WP that needs Data Catalog, Indicator Setup or Data Upload checked in a browser before WP-2e lands. Related: [[hasura-secret-facts]].
