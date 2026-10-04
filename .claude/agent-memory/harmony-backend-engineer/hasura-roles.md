---
name: hasura-roles
description: WP-0a Hasura role model (user/anonymous), what was deliberately left loose for WP-5e, and the tools that prove GraphQL parity
metadata:
  type: project
---

WP-0a (branch `mig/WP-0a-lock-down-hasura`, 2026-10-04) put Hasura behind an admin secret. The Flask proxy sends `X-Hasura-Role: user` for any signed-in user and `anonymous` for public-access visitors.

- On main, public-access deployments let an anonymous visitor run any admin mutation. The proxy only checks that the query text starts with `query patchDimensionServiceQuery`, so a second operation chosen with `operationName` slips through. The `anonymous` role (select on the dimension tables only) closes this.
- Still loose, deliberately (INV-3): any signed-in user can edit catalog, field setup and upload tables through GraphQL, whatever their Flask site permissions. WP-5e must add `can()` checks when porting the catalog.
- `scripts/db/hasura/check_role_permissions.py` (static, per-role introspection) and `scripts/db/hasura/replay_relay_operations.py` (57 steps through the real Flask proxy, with `--compare`) are the parity levers. Reuse the replay's variables as WP-5e contract cases.
- Relay node ids are identical on Hasura v2.11.3 and v2.45.8. v2.45 has no catalog `downgrade`; rollback is dropping `hdb_catalog` and reapplying metadata.
- Hasura traps that reviewers caught:
  - An *empty* `HASURA_GRAPHQL_ADMIN_SECRET` makes `''` the secret, so an empty header gets admin. Never describe it as "no secret".
  - The plain `v2.45.8` tag runs the EE binary in fallback mode; use the `-ce` tag.
  - `HASURA_GRAPHQL_ENABLED_APIS=graphql,metadata` keeps `/v1beta1/relay` working.
  - A missing secret on GraphQL endpoints is HTTP 200 with `access-denied`, not 401.
- Anonymous can still smuggle a second *read* on the 6 public columns (no depth limit). The pre-5e fix is hash-matching compiled operations in the proxy. Hasura's allowlist rejects Relay `*_connection` queries.
- Reviewers expect, for any script a WP adds: pinned dependencies (uv `--script` lockfile), secrets only from env (never argv), and destructive tools refusing unless the DB is explicitly marked disposable.

**Why:** WP-5e retires Hasura and must not regress either the closed hole or the UI's operations.
**How to apply:** start WP-5e from these scripts and from the 17-table list in `graphql/hasura/metadata/versions/latest/tables.yaml`. [[local-flask-stack]]
