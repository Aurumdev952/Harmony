# 0004. Widen WP-0h; add WP-0i for the render and thumbnail routes

Status: applied by the lead on 2026-10-05, pending human ratification (SPEC section 10). Amends decision 0003.

## Context

The security review of WP-2b (the authorisation suite) reproduced further escalation and exposure paths on a fresh `harmony_demo` stack:

- **N3** A `role_moderator` can `PATCH /api2/role/<id>` on a role it holds to add any permission (for example `view_admin_page`).
- **N4** `build_role` looks query policies up with `find_by_id`, bypassing the resource filter, so a `role_administrator` can attach the seeded all-values policies to a role and lift its own row-level filter; `dataExport` is accepted the same way.
- **N5** A `group_moderator` can attach a role that carries all-values policies (for example `_default_role`) to its group and gain them.
- **N6** `PATCH /api2/role/<id>/users` lets a moderator grant a role it holds to other users (code reading).
- The WP-0h interrogate also found that a `group_moderator` can add themselves (`POST /api2/group/<id>/users`) to a group that holds admin, and that `PATCH /api2/group/<id>/roles` with an empty map reaches `session.delete` on `Role` rows.
- **N1** `/dashboard/<slug>/png/thumbnail` (`web/server/routes/page_renderer.py:64-67, 94-103`) has no authentication or authorisation; the server mints a render-bot JWT (the render bot is created as a site admin by `scripts/create_bot_accounts.sh`) and returns the rendered PNG to an anonymous caller.
- **N2** `/api2/storage/retrieve` serves those render-bot thumbnails, cached per slug for two weeks, to viewers whose query policy restricts them (`web/server/redis/thumbnail_storage_service.py:14-38`).

## Decision

1. **WP-0h scope** covers every path by which a caller can grant, to itself or others, a role, permission, query policy or data-export right it could not grant directly: the three decision-0003 escalations plus N3, N4, N5, N6, the `/users` self-add and the `/roles` empty-map deletion. Rule: a non-superuser caller may attach or confer only grants it already holds; refusals are 403 with an audit line; existing grants on a resource may be re-sent unchanged.
2. **WP-0i: Guard the dashboard render and thumbnail routes** is added to SPEC section 5: owner `backend`, supporting `security, qa`, depends on none, Sec yes. Scope: the render routes (`/dashboard/<slug>/png/thumbnail`, `/pdf`, `/jpeg` and any other `page_renderer` route) require an authenticated caller with `view_resource` on that dashboard, the same check the dashboard page itself applies; `/api2/storage/retrieve` serves a thumbnail only to a caller allowed to view the dashboard, and the cache key includes the viewer's policy (or thumbnails for policy-restricted viewers are rendered as the requesting user) until WP-1h replaces the renderer; the render bot stops being a site admin if the renderer can run under the requesting user's token, otherwise the bot's scope is recorded as a carried risk for WP-1h. Every outcome change goes in an INV-3 table accepted by security and the human.
3. WP-2b pins all of the above as today's behaviour; WP-0h and WP-0i flip the pins in their own stacks, by qa.

## Consequences

- SPEC 1.4: WP-0i row; WP-0h row text unchanged, scope defined here and in phase-0 section 0h.
- Phase 0 gains section 0i.
