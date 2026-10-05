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
- Druid has no authenticator. Since WP-0b R4.6, its ports bind to `DRUID_BIND_ADDRESS` (single mode) or to `DRUID_MASTER_HOST`/`DRUID_DATA_HOST`/`DRUID_QUERY_HOST` (cluster mode), and tests fail on any 0.0.0.0 publication. The lead plans authentication for WP-8a/8b.
- `make *_up` runs `check_secrets`, which refuses an empty or old-default password and an unpinned `DRUID_POSTGRES_IMAGE`. Compose `${VAR:?}` only rejects empty values, so value checks belong in the Makefile. `tests/druid_setup/test_druid_makefile.py` tests them with a stub `docker` on PATH.
- The reviewers run black 22.6 with `-S -t py39` on tests: `uvx --from 'black==22.6.0' black -S -t py39 --check tests/druid_setup`.

**Why:** These facts cost a session to establish and none of them can be seen in the code.
**How to apply:** Read this before touching druid_setup in WP-8b (upgrade, ZooKeeper removal) or WP-8a (JavaScript off).
