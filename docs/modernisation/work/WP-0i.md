---
wp: "0i"
title: "Guard the dashboard render and thumbnail routes"
status: claimed
owner_role: "backend"
instances:
  - name: "backend-7"
    files:
      - web/server/routes/page_renderer.py
      - web/server/routes/views/page_renderer.py
      - web/server/redis/thumbnail_storage_service.py
      - web/server/api/thumbnail_storage_api_models.py
      - tests/web/**
      - docs/modernisation/work/WP-0i.md
branch: "mig/WP-0i-render-route-guards"
requirements: [SEC-7]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0i: Guard the dashboard render and thumbnail routes

Decision 0004, phase 0 section 0i. Closes N1 (anonymous thumbnail render under the render bot's admin token) and N2 (render-bot thumbnails served from a per-slug cache to policy-restricted viewers). SEC-7 is only partly met here; WP-1h owns the scoped render token.

## Plan

1. `pstack:how` on the render routes, render-token minting, the thumbnail cache, `/api2/storage/retrieve`, and the dashboard page's `view_resource` check. Check: findings recorded below.
2. Failing tests under `tests/web/` with the renderer HTTP call mocked. Check: they fail on the base for the reasons N1 and N2 describe.
3. The fix: every `page_renderer` route requires an authenticated caller with `view_resource` on the dashboard; `/api2/storage/retrieve` serves a thumbnail only to a caller who may view the dashboard, and never a thumbnail rendered under a wider policy (approach chosen with `pstack:interrogate`). Check: unit 2 tests green.
4. The render bot: stop minting the bot token if the renderer can run as the requesting user, else record the carried risk for WP-1h. Check: tests and code reading.
5. INV-3 before and after table. Check: table below.
6. WP-2b pure layer against the fix in a scratch copy; request qa-2b to flip the N1 and N2 pins. Check: `tests/authz/run.sh` output.

## Contract changes

None.

## Requests

## Log

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
