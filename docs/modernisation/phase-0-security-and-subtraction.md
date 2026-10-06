# Phase 0. Security and subtraction

Back to [overview](overview.md).

**Goal.** Close the open exposures and delete code and dependencies that nothing uses. This shrinks every later phase. Nothing in this phase changes behaviour for users.

Each unit is one PR.

## 0a. Lock down Hasura

- **Changes.**
  - Set `HASURA_GRAPHQL_ADMIN_SECRET` in `docker-compose.yaml` and stop publishing port 8088. Do not set `HASURA_GRAPHQL_UNAUTHORIZED_ROLE`: in admin-secret mode it serves requests without the secret as that role, which defeats the lockdown (WP-0a decision).
  - Have the Flask proxy (`web/server/routes/api.py:144-176`) send the admin secret plus `x-hasura-role` and `x-hasura-user-id` headers from `current_user`.
  - Pass `apply_metadata_snapshot.py` the secret.
  - Upgrade Hasura to v2.45 LTS in the same PR, since v2.11 has been out of support since 2024-09. It is an interim step; phase 5 retires Hasura.
- **Verification.**
  - From the host, a direct `curl` to Hasura fails without the secret.
  - Data Catalog, Field Setup and Data Upload load and save through the proxy (`verify` skill).

## 0b. Close the published ports and default secrets

- **Changes.**
  - Remove the host port mappings for Redis (6379), the worker (61234) and Postgres (5432) from the base Compose file. Keep them in `docker-compose.dev.yaml` only, bound to `127.0.0.1`.
  - Add `requirepass` to Redis.
  - Fail startup when `DEFAULT_SECRET_KEY` is `changeme` or empty.
  - Split `JWT_SECRET_KEY` from `SECRET_KEY` (`web/server/configuration/flask.py:34`).
  - Druid setup:
    - replace `FoolishPassword`,
    - stop publishing ZooKeeper, memcached and Postgres,
    - pin `postgres` and `minio` images,
    - pin the Druid extension downloads to a tag and checksum (`druid_setup/extensions/load_extensions.sh:286`).
- **Verification.**
  - `docker compose config` shows no unintended published ports.
  - Startup with the default key exits non-zero with a clear message.
  - `make up` works with a `.env` that sets real keys.

## 0c. Fix the bugs that are pure mistakes

- **Changes.** Each fix gets a regression test, even before phase 2 exists, as a plain pytest file run locally.
  - `docker-compose.pipeline.yaml:17`: delete the `POSTGRES_DB_URI:=` line. Nothing reads `POSTGRES_DB_URI`; Alembic reads `SQLALCHEMY_DATABASE_URI`, which comes from `DATABASE_URL`.
  - `web/server/routes/dashboard.py:44`: point at the correct blueprint endpoint.
  - `web/server/util/util.py:622`: `is_session_persisted` reads the `accessKey` cookie's persistence instead of `remember_token`.
  - `run_raw_query`: apply the query policy, or restrict callers to service code. Decide this with `pstack:interrogate`.
- **Verification.** A failing test before each fix and a passing one after.

## 0d. Delete dead backend code and dependencies

- **Changes.**
  - Remove from the requirements files: Flask-Admin, graphene-sqlalchemy, Flask-GraphQL, dask, google-cloud-logging, segment-analytics-python, paramiko and its pins, fuzzywuzzy, jellyfish, editdistance.
  - Delete the empty `/graphql` route and its module (`web/server/routes/graphql_api.py`, `web/server/graphql/`).
  - `/api/timeout` is live (the client's inactivity sign-out posts to it); keep it.
  - Delete the Hadoop task templates (`db/druid/indexing/resources/task_templates`, `tuning_configs/on_prem.json`) together with `legacy_task_builder.py`, which reads them at import, and `scripts/run_indexing.py`, which nothing references.
  - Delete `web/client/util/graphql/zen_environment.js` and its re-export in `index.jsx`; nothing uses it.
- **Verification.** Images build. Every page and every Potion resource still responds; use the smoke list in [testing.md](testing.md). `grep` confirms no imports of the removed packages.

## 0e. Delete dead frontend code and dependencies

- **Changes.**
  - Remove from `package.json`: papaparse, simple-statistics, d3-random, d3-scale-chromatic.
  - Remove templates that no route renders: `query.html` and `facilities_map.html`.
  - Remove the `asyncMapChunk` reference from `grid_dashboard.html`.
  - Remove `bootstrap-5.2.0.js` from `layout.html`.
  - Remove bootstrap-select and bootstrap-datepicker from `query_app_vendor_scripts.html`, together with their SCSS.
  - Ask product whether Alerts should be revived or deleted. Today the route renders 404 (`web/server/routes/index.py:69-73`).
- **Verification.** `yarn build` passes. Every page renders without console errors (`verify` skill, all 15 page routes).

## 0f. One CI system and one branch name

- **Changes.**
  - Delete `ci/docker/Jenkinsfile`, or fix its targets if a deployment still depends on it. Ask first.
  - Change the Makefile default `COMMIT?=master` to `main`.
  - Bump the GitHub Actions to their v4/v5 majors.
  - Replace `permissions: write-all` with per-job least privilege.
  - Pin `ubuntu-24.04` across all jobs.
- **Verification.** Every workflow goes green on a PR.

## 0g. Measure browsers before choosing a CSS baseline

- **Changes.** Add a script that summarises user agents from production nginx access logs, sorted by deployment.
- **Data structure.** `BrowserShare = {family, major, share_pct}` per deployment.
- **Verification.** It runs against one deployment's logs. The share of sessions below Chrome 111, Safari 16.4 or Firefox 128 is recorded in the phase 7 decision log. If more than 5% of sessions fall below that line, phase 7 needs a fallback plan before it starts.

## 0h. Close the privilege escalations in group and role management

Added by decision 0003 after WP-2b reproduced them; scope widened by decision 0004 (N3 to N6, the `/users` self-add and the `/roles` empty-map deletion). Rule: a non-superuser caller may attach or confer only grants it already holds, on roles, groups, query policies and data export alike; existing grants may be re-sent unchanged.

- **Changes.**
  - `POST /api2/group` and `PATCH /api2/group/<id>`: resolve role URIs through the `RoleResourceManager` filter, and refuse to attach a role the caller could not grant directly (the admin role needs sitewide admin; resource roles need the matching resource permission).
  - `POST /api2/role` and `PATCH /api2/role/<id>`: creating or editing a role with permissions or resource roles passes the same `update_permissions` gate as editing permissions directly; the creator is not auto-added unless the caller may grant that role.
  - Audit log entries for every refused attempt.
- **Verification.**
  - The three WP-2b escalation cases flip from pinned to refused (403) in the same change.
  - The rest of the WP-2b table is unchanged: no other role loses or gains anything.
  - The INV-3 difference table in the WP file is accepted by security and the human.

## 0i. Guard the dashboard render and thumbnail routes

Added by decision 0004 after the WP-2b security review.

- **Changes.**
  - `/dashboard/<slug>/png/thumbnail`, `/pdf`, `/jpeg` and every other `page_renderer` route require an authenticated caller with `view_resource` on that dashboard, the same check the dashboard page applies.
  - `/api2/storage/retrieve` serves a thumbnail only to a caller allowed to view the dashboard; the cache key includes the viewer's policy, or thumbnails for policy-restricted viewers are rendered as the requesting user, until WP-1h replaces the renderer.
  - The render bot stops being a site admin if the renderer can run under the requesting user's token; otherwise record the bot's scope as a carried risk for WP-1h.
- **Verification.**
  - Anonymous and unauthorised requests to every render route get 401 or 403 and no outbound render call is made (mock the renderer; never call urlbox from tests).
  - A policy-restricted viewer never receives a thumbnail rendered with a wider policy.
  - The WP-2b pins for these routes flip from today's behaviour to the new one in the same stack.

## 0j. Refuse username changes and password resets that reach a higher-privileged account

Added by decision 0005 after the WP-0h security re-review confirmed H5 live.

- **Changes.**
  - `PATCH /api2/user/<id>` refuses a `username` change, and `POST /api2/user/<id>/reset_password` refuses the reset, when the caller is not a superuser and the target holds any grant the caller does not (roles direct or through a group, group memberships, ACLs, query policies, data export; administrator by any path). Refusals are 403, write nothing and leave an audit line.
  - Optional, with security: `UserResourceManager` hides users who are administrators through a group from non-superusers, as it already hides direct administrators.
- **Verification.**
  - A failing test first: `manager` + `user_admin` renaming an admin-through-group user gets 200 on the base and 403 on the branch with no row changed and no reset mail; the stubbed mailer receives nothing.
  - Equal-or-lesser targets still rename and reset as before.
  - The WP-2b pins for these routes flip in the same stack; the INV-3 row in decision 0005 is accepted by security and the human.

## 0k. Build outgoing links from the configured origin; match usernames exactly

Added by decision 0006 after the WP-0i round-2 reviews.

- **Changes.**
  - Reset, invite, access-granted, new-dashboard and share-by-email links are built from `DEPLOYMENT_BASE_URL` through WP-0i's helper; nothing reads the request Host or `SCRIPT_NAME`. `send_email` links to the dashboard's own page and ignores the caller's free-form URL.
  - Login, registration and invitation look users up by exact `lower(username)`; the JWT identity is `user.username`.
- **Verification.**
  - Failing tests first: a forged Host (`attacker.invalid`, `real.org:@attacker.invalid`) and a forged `SCRIPT_NAME` on `forgot_password`, invite, access-granted and new-dashboard paths produce links on the configured origin; a look-alike username (`john_doe` for `john.doe`) no longer signs in as the other account.
  - Unit 1 records whether nginx-proxy 1.11.6 forwards the raw Host on a local stack.
  - The WP-2b pins flip in the same stack; the INV-3 rows are accepted by security and the human.

## 0l. Match resource, role, group and user names exactly, never as patterns

Added by decision 0012 after the WP-0k QA gate and a security rating.

- **Changes.**
  - `find_one_by_fields(..., case_sensitive=False)` compares `lower(field) == lower(value)`; `_` and `%` in a chosen name are literal.
  - Sharing and share removal act on the resource and principals they were given; nothing re-finds a resource by its own name.
  - 403 bodies from grant checks do not repeat resource names.
  - Tests settle the three tracing notes in decision 0012 (resource type dropped by Python `and`; legacy `/roles` POST routes; empty `PATCH /roles` body).
- **Verification.**
  - Failing tests first (qa): sharing dashboard `a_b` never touches `axb`; removing a share for `john_doe@…` leaves `john.doe@…` untouched; adding `john_doe@…` to a group never adds `john.doe@…`.
  - The WP-2b pins flip in the same stack; the INV-3 rows are accepted by security and the human.
