---
name: local-yarn-build
description: How to get yarn install and yarn build working locally on Node 24 for the legacy webpack frontend (ENETUNREACH, node-pty failure, Docker node:18.17 check)
metadata:
  type: reference
---

- `yarn install` fails with `ENETUNREACH` on this host (IPv6 first). Prefix with `NODE_OPTIONS="--dns-result-order=ipv4first"`.
- `yarn install --frozen-lockfile` on Node 24 fails building `node-pty` 0.10 (pulled in by the dev-only `stylelint_d`). Add `--ignore-scripts`; nothing the webpack build needs has an install script. Then `yarn build` passes on Node 24 in about 40 s.
- The shipped image is `docker/web/Dockerfile_web-client` on `node:18.17` (until WP-6b moves it to Node 24). `docker build -f docker/web/Dockerfile_web-client .` runs the real frozen install and production build; extract `/client/build` from two images to diff bundles byte for byte.
- `flow check` on `main` already reports 19 errors (GIS tile, DashboardService, Insights). Compare the error set, not the exit code.
- Webpack output lands in `web/public/build/min/`.
- In an isolated worktree, the sandbox refuses Bash commands that combine `git` with loops, `$var` expansion or `--exclude-dir=.git`. Run git commands on their own line.

Related: [[full-stack-page-check]]
- Grepping `web/` for a symbol also hits stale webpack source maps in `web/public/build/` (megabytes of output). Pass `--exclude-dir=build --exclude-dir=node_modules`.
- `flow check` and eslint print `node[<pid>]: pthread_create: Invalid argument` on this host. It is noise; diff full flow output and ignore that line.
