---
wp: "0b"
title: "Close published ports, refuse default secrets, pin images"
status: building
owner_role: "infra"
instances:
  - name: "infra-1"
    files:
      - docker-compose.yaml
      - docker-compose.dev.yaml
      - docker-compose.db.yaml
      - docker-compose.minio.yaml
      - docker-compose.pipeline.yaml
      - docker/**
      - tests/infra/**
branch: "mig/WP-0b-ports-secrets-pins"
requirements: [SEC-1, SEC-3, SEC-9]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0b: Close published ports, refuse default secrets, pin images

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Claim. Check: file committed on the branch.
2. Fix `POSTGRES_DB_URI:=` in `docker-compose.pipeline.yaml` (handed over from WP-0c by the lead). Check: `tests/infra/test_compose.py::test_pipeline_passes_postgres_db_uri` fails before, passes after.
3. Close published ports. Base file publishes only nginx (drop redis 6379, worker 61234, web 5000). Dev overlay binds postgres, redis and web to `127.0.0.1`. `docker-compose.db.yaml` and `docker-compose.minio.yaml` need an explicit bind address. Check: port tests over every overlay combination, plus `docker compose config` evidence.
4. Refuse empty and default secrets at the Compose layer. `DEFAULT_SECRET_KEY`, `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `MINIO_ROOT_*` use `${VAR:?message}`; the `:-changeme` fallbacks go. Check: tests that `config` exits non-zero with the message when unset, and that `changeme` appears nowhere in the rendered config.
5. Redis `requirepass`. Check: a throwaway Redis from the compose definition rejects unauthenticated commands, the healthcheck passes, and the worker's broker URL authenticates. Merge-blocked on backend request R2.
6. Pin Compose images (nginx-proxy, acme-companion, redis, postgres) by tag and digest. Check: test that every `image:` outside our own builds carries `@sha256:`; `docker buildx imagetools inspect` resolves each.
7. Pin Dockerfile base images by digest and every download by checksum (mc, flow, pypy, CPython). Check: `docker build --check` on each Dockerfile; build the `downloader` stages so checksums are exercised; build the web-server image.
8. Runtime check: bring up postgres, redis and hasura from the dev overlay under a throwaway project name, confirm `docker compose ps` publishes only `127.0.0.1`, tear down.

## Contract changes

None.

## Requests

- [ ] R1 core: in `config/settings.py:16`, refuse to import when `DEFAULT_SECRET_KEY` is unset, empty or `changeme` (case-insensitive, stripped). Raise `RuntimeError('DEFAULT_SECRET_KEY must be set to a random value, e.g. `openssl rand -hex 32`; refusing to start with an empty or default key')` so web, worker, pipeline and every script exit non-zero with that message. Add a unit test under `tests/core/`. Compose already refuses unset/empty (unit 4); this covers an explicit `changeme` and non-Compose runs. SEC-3. (blocks WP close, not a unit)
- [ ] R2 backend: Redis password. `web/server/configuration/celery.py:get_broker_url`: when `REDIS_HOST` is set, build `redis://:{quote(REDIS_PASSWORD, safe="")}@{host}:6379/` if `REDIS_PASSWORD` is set (unchanged URL otherwise). `web/server/configuration/flask.py` `CACHES['redis']`: add `'CACHE_REDIS_PASSWORD': getenv('REDIS_PASSWORD') or None`. Compose (unit 5) passes `REDIS_PASSWORD` to web and worker. Without this change the web container's cache and Celery client fail auth against the new Redis, so **WP-0b must not merge before R2 lands** (same stack). (blocks merge of unit 5)
- [ ] R3 backend: split the JWT key (`web/server/configuration/flask.py:34`). `SECRET_KEY = getenv('SECRET_KEY', settings.DEFAULT_SECRET_KEY)`; `JWT_SECRET_KEY = getenv('JWT_SECRET_KEY')`; raise at startup if `JWT_SECRET_KEY` is empty, `changeme`, or equal to `SECRET_KEY`. Compose already passes a required `JWT_SECRET_KEY` to web and worker (unit 4). Existing `accessKey` cookies and API tokens become invalid once, so users sign in again; say so in the release note. SEC-3. (blocks WP close)
- [ ] R4 data-platform: Druid setup items from phase 0b, all in `druid_setup/**`:
  - replace `FoolishPassword` (`single/docker-compose.yml:59`, `single/environment/common.env:25`, `cluster/cluster.env:8`) with a required variable (`${DRUID_POSTGRES_PASSWORD:?...}` in Compose, and read it from the env in `common.env`);
  - stop publishing ZooKeeper 2181, memcached 11211 and Postgres (5431/5432) in `single/docker-compose.yml` and `cluster/docker-compose-master.yml`; bind to `127.0.0.1` where a host tool needs them, or to a private interface variable where another host does (cluster mode);
  - pin `postgres:latest` and `memcached` by tag and digest (current: `postgres:15.19-alpine@sha256:f7d23353e1b15400d22ebe31189f4d314b87a4c129cc400c8c2d8d4ca127bf81`; check the major matches the existing metadata volume before choosing), and `zookeeper:${ZOOKEEPER_VERSION}` / `apache/druid:${DRUID_VERSION}` defaults by digest;
  - pin the extension downloads in `extensions/load_extensions.sh:26-35` (they fetch `raw/master` from GitHub) to a commit or tag and verify each with `sha256sum -c`.
  (blocks WP close, not a unit)
- [ ] R5 human: MinIO no longer publishes server images. `minio/minio` on Docker Hub returns "repository does not exist" and `quay.io/minio/minio` returns 401, so `docker-compose.minio.yaml` cannot be pinned or even pulled on a fresh host. Existing hosts keep their cached image. Choose a replacement (a maintained fork image, a source build we publish to `ghcr.io/zenysis`, or another S3-compatible store such as Garage or SeaweedFS). Unit 6 leaves the `minio/minio:latest` line as is until you decide. (does not block other units)
- [ ] R6 human: `.env.example` is infra-owned but agent settings deny reading it (it matches `.env*`). Add `DEFAULT_SECRET_KEY=`, `JWT_SECRET_KEY=`, `REDIS_PASSWORD=` (all generated with `openssl rand -hex 32`), and for separate-host setups `POSTGRES_BIND_ADDRESS=` and `MINIO_BIND_ADDRESS=`, and remove any `changeme` value. Also update the README production `.env` sample (human-owned) with the same keys. (blocks WP close)
- [ ] R7 backend (WP-0a): the Hasura port 8088 and image upgrade stay with WP-0a. When WP-0a asks, infra edits the `hasura` service; until then this WP leaves that service alone, so `docker compose config` on this branch still shows 8088 published.

## Log

- 2026-10-04 infra-1 unit 1: claimed WP-0b; check: commit 4acd856.
- 2026-10-04 infra-1 unit 2: `POSTGRES_DB_URI:=` becomes `POSTGRES_DB_URI=` in `docker-compose.pipeline.yaml` (handed over from WP-0c); check: `uv run --no-project --with pytest pytest tests/infra` failed before (env key was `POSTGRES_DB_URI:`), 1 passed after.
- 2026-10-04 infra-1 unit 3: base file publishes only nginx (redis, web, worker ports removed); dev binds postgres, redis, web to 127.0.0.1; db/minio files require an explicit bind address; check: `pytest tests/infra` 6 new tests failed before, 7 passed after; port summary under Evidence.

## Evidence

### Unit 3: published ports (`docker compose config`, dummy env file, no `.env`)

Before (main): the base file published nginx 80/443, redis 6379, hasura 8088, web 5000 and worker 61234 on `0.0.0.0`; dev published postgres 5432 on `0.0.0.0`.

After:

```
## docker-compose.yaml (+ prod, + local: identical)
hasura: 0.0.0.0:8088->8080      # WP-0a removes this (R7)
nginx: 0.0.0.0:80->80, 0.0.0.0:443->443
## docker-compose.yaml + docker-compose.dev.yaml
hasura: 0.0.0.0:8088->8080      # WP-0a
postgres: 127.0.0.1:5432->5432
redis: 127.0.0.1:6379->6379
web: 127.0.0.1:5000->5000
## docker-compose.db.yaml without POSTGRES_BIND_ADDRESS
error while interpolating services.postgres.ports.[]: required variable POSTGRES_BIND_ADDRESS is missing a value: set POSTGRES_BIND_ADDRESS to 127.0.0.1 when web runs on this host, or to this host's private IP when it runs elsewhere
```

The worker port 61234 had no listener behind it (Celery needs no inbound port), so dev does not re-add it.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
