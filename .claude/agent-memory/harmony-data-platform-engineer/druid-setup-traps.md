---
name: druid-setup-traps
description: Non-obvious facts about druid_setup Compose (password provider, Postgres major pinning, ports, extension table) learned in WP-0b R4
metadata:
  type: project
---

- Druid's docker entrypoint (`druid.sh`, 0.23) echoes every `druid_*` env var as "Setting key=value" into the container log. Secrets go through the `environment` password provider (`{"type": "environment", "variable": "DRUID_POSTGRES_PASSWORD"}`), with the variable passed to the coordinator only. Peons publish via the overlord and do not need it (verified by an inline ingest on 2026-10-04).
- The Druid metadata Postgres was `postgres:latest`, so hosts may be on 14 to 17. It is pinned to 17.11-bookworm, and `DRUID_POSTGRES_IMAGE` overrides it. Keep the Debian variant, because Alpine collation breaks the text indexes. `postgres:18` refuses the `/var/lib/postgresql/data` mount.
- The Postgres image applies `POSTGRES_PASSWORD` only on the first initdb. Rotating the password needs `ALTER USER`.
- Cluster mode: ZooKeeper and Postgres bind to `${DRUID_MASTER_HOST}`, not 0.0.0.0. Memcached is unused in cluster mode (it has no `druid_cache_type`).
- The extension versions live in the checksum table in `druid_setup/extensions/load_extensions.sh`. A test ties them to the `apache/druid:<ver>@sha256` tag. WP-8b must replace every line of that table.
- Druid HTTP ports are still published unauthenticated on 0.0.0.0 with JavaScript enabled. This is open (flagged in WP-0b deferrals).

**Why:** These facts cost a session to establish and none of them can be seen in the code.
**How to apply:** Read this before touching druid_setup in WP-8b (upgrade, ZooKeeper removal) or WP-8a (JavaScript off).
