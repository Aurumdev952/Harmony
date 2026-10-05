---
name: render-bot-is-site-admin
description: Export and thumbnail renders run as the render bot, which deployments create as a site admin, so render-bot renders bypass every query policy; the Flask thumbnail route had no auth at all (found 2026-10-04)
metadata:
  type: project
---

`scripts/create_bot_accounts.sh` creates `renderbot@zenysis.com` with `-a` (`--site_admin`). `grid_dashboard_urlbox_renderer` defaults `auth_user_email` to `settings.RENDERBOT_EMAIL`. With an explicit `needs` list the admin loses `RoleNeed('admin')`, but `_compute_token_query_needs` takes its superuser branch first and keeps `query_needs: ['*']` verbatim, so the render has **no row-level filter**.

As found in the WP-2b review (2026-10-04):
- `/dashboard/<slug>/png/thumbnail` (and the `/<locale>/` form) had no authentication and no authorisation. It minted a render-bot JWT, sent it to urlbox.io and streamed the PNG to an anonymous caller.
- `/api2/storage/retrieve?key=<slug>` checks `view_resource` but serves render-bot thumbnails, cached for 2 weeks per slug, to policy-restricted viewers.
- PDF and JPEG exports for signed-in users use `current_user.username`, which is correct. The public-user PDF uses the render bot.

**Why:** this is the main SEC-4/SEC-7 trap in the export path. Signed-in renders look scoped, but the default argument quietly makes the render bot (an admin) the principal.
**How to apply:** in any WP touching exports, thumbnails, WP-1h or WP-5f, check which principal the render token is minted for and whether the cache key includes the policy. Re-check that the thumbnail route is guarded before closing phase 0.
