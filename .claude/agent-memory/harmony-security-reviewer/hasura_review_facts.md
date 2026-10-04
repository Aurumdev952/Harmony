---
name: hasura-review-facts
description: Hasura facts verified in the WP-0a review that matter until WP-5e retires it - allowlist cannot hold Relay ops, advisories, EE vs CE image, residual user-role risk
metadata:
  type: project
---

Verified on a local stack (Hasura v2.45.8, 2026-10-04):

- **The CE allowlist is not a bridge for Relay.** `HASURA_GRAPHQL_ENABLE_ALLOWLIST=true` is enforced on `/v1beta1/relay` for non-admin roles ("query is not allowed"). But `create_query_collection` validates queries against the `/v1/graphql` schema, which has no `*_connection` fields, so no Relay operation can be listed. Turning it on denies every UI call. To pin `user` to the 51 compiled operations before WP-5e, hash-match the request's query text in the Flask proxy instead.
- **Advisories.** v2.11.3 (main before WP-0a) is in GHSA-c9rw-rw2f-mj4x (critical path traversal, fixed in 2.11.5). It needs `HASURA_GRAPHQL_CONSOLE_ASSETS_DIR`, which only the dev script `start_graphql_engine.sh` sets. GHSA-r27x-gc74-qmxh (computed-field row-filter bypass) is fixed in 2.45.5. Harmony metadata has no computed fields.
- **Image.** The non-`-ce` tag runs the EE binary (`HGE_BINARY=graphql-engine-pro`) in CE fallback, as root. A `v2.45.8-ce.cli-migrations-v2` multi-arch image exists.
- **Defaults seen in the startup log:** `enabled_apis` = metadata, config, pgdump, graphql; `cors_config.allowed_origins` = `*`; the console is off unless enabled.
- **Residual risk accepted into WP-5e:** the `user` role keeps unfiltered insert/update/delete on catalog and upload tables, for every signed-in user. `mutation { delete_field(where: {}) }` works. `data_upload_file_summary.file_path` is client-writable and is joined into object-storage keys (`self_serve_connection.py` `get_file_key`). That lead is unverified.

**Why:** WP-5e and any later Hasura change will be reviewed against these.
**How to apply:** when reviewing WP-5e or touching Hasura metadata or the proxy, start from these facts and re-check them on the current version. [[review-tooling-traps]]
