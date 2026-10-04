---
wp: "0b"
title: "Close published ports, refuse default secrets, pin images"
status: review
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
      - requirements.txt
  - name: "data-platform-1"
    branch: "mig/WP-0b-ports-secrets-pins-druid"
    files:
      - druid_setup/**
      - tests/druid_setup/**
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
2. Remove the `POSTGRES_DB_URI:=` line from `docker-compose.pipeline.yaml` (handed over from WP-0c). Nothing reads `POSTGRES_DB_URI`: Alembic takes `SQLALCHEMY_DATABASE_URI` from the Flask config (`web/server/migrations/env.py:23-24`), and the pipeline already sets that from `DATABASE_URL`. Check: `test_pipeline_does_not_set_unread_postgres_db_uri` and `test_no_environment_key_contains_a_colon`.
3. Close published ports. Base file publishes only nginx (drop redis 6379, worker 61234, web 5000). Dev overlay binds postgres, redis and web to `127.0.0.1`. `docker-compose.db.yaml` and `docker-compose.minio.yaml` need an explicit bind address. Check: port tests over every overlay combination, plus `docker compose config` evidence.
4. Refuse empty and default secrets at the Compose layer. `DEFAULT_SECRET_KEY`, `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `MINIO_ROOT_*` use `${VAR:?message}`; the `:-changeme` fallbacks go. Check: tests that `config` exits non-zero with the message when unset, and that `changeme` appears nowhere in the rendered config.
5. Redis `requirepass`. Check: a throwaway Redis from the compose definition rejects unauthenticated commands, the healthcheck passes, and the worker's broker URL authenticates. Merge-blocked on backend request R2.
6. Pin Compose images (nginx-proxy, acme-companion, redis, postgres) by tag and digest. Check: test that every `image:` outside our own builds carries `@sha256:`; `docker buildx imagetools inspect` resolves each.
7. Pin Dockerfile base images by digest and every download by checksum (mc, flow, pypy, CPython). Check: `docker build --check` on each Dockerfile; build the `downloader` stages so checksums are exercised; build the web-server image.
8. Runtime check: bring up postgres and redis from the dev overlay under a throwaway project name, confirm `docker compose ps` publishes only `127.0.0.1`, tear down.
9. Pin `bcrypt==4.0.1` next to `flask-user` in `requirements.txt` (raised by WP-0a: `scripts/create_user.py` hashes through passlib 1.7.4, and bcrypt was unpinned). Check: `tests/infra/test_requirements.py` fails without a pin and passes with it; web-server image rebuilt and hashes a password.
10. R8: the worker gets `REDIS_HOST=redis` and `REDIS_PASSWORD` instead of a hand-built `BROKER_URL`, so `get_broker_url` builds and URL-encodes the URL, and the "must be URL-safe" note on `redis` goes. Check: `test_redis_requires_auth_and_clients_carry_the_password` asserts both clients get host and password and neither gets `BROKER_URL`.

Request R4 (data-platform-1, branch `mig/WP-0b-ports-secrets-pins-druid`, files `druid_setup/**`, `tests/druid_setup/**`):

- R4.1 Druid metadata password from a required variable. Check: `tests/druid_setup` fails before, passes after.
- R4.2 Stop publishing ZooKeeper, memcached and Postgres. Check: port test over all four Druid Compose files.
- R4.3 Pin postgres, memcached, ZooKeeper, Druid and the extension loader's base image by tag and digest. Check: pin test; `docker buildx imagetools inspect` per tag.
- R4.4 Pin the extension downloads to a commit and verify each with `sha256sum -c`. Check: checksum-coverage test; build and run the extension loader.
- R4.5 Runtime check of the single-server setup on throwaway volumes.

## Contract changes

None.

## Requests

- [x] R1 core (core-3, branch `mig/WP-0b-ports-secrets-pins-core`, done): in `config/settings.py:16`, refuse to import when `DEFAULT_SECRET_KEY` is unset, empty or `changeme` (case-insensitive, stripped). Raise `RuntimeError('DEFAULT_SECRET_KEY must be set to a random value, e.g. `openssl rand -hex 32`; refusing to start with an empty or default key')` so web, worker, pipeline and every script exit non-zero with that message. Add a unit test under `tests/core/`. Compose already refuses unset/empty (unit 4); this covers an explicit `changeme` and non-Compose runs. SEC-3. (blocks WP close, not a unit)
  - core-3 note for R3: `flask.py` reads `getenv('SECRET_KEY', settings.DEFAULT_SECRET_KEY)`, so an env `SECRET_KEY` overrides the checked key and is itself unchecked. R3 should read every signing key through `config.settings.require_secret(name)` (same rule and message as R1) or drop the `SECRET_KEY` override.
- [x] R2 backend (backend-4, branch `mig/WP-0b-ports-secrets-pins-backend`, done): Redis password. `web/server/configuration/celery.py:get_broker_url`: when `REDIS_HOST` is set, build `redis://:{quote(REDIS_PASSWORD, safe="")}@{host}:6379/` if `REDIS_PASSWORD` is set (unchanged URL otherwise). `web/server/configuration/flask.py` `CACHES['redis']`: add `'CACHE_REDIS_PASSWORD': getenv('REDIS_PASSWORD') or None`. Compose (unit 5) passes `REDIS_PASSWORD` to web and worker. Without this change the web container's cache and Celery client fail auth against the new Redis, so **WP-0b must not merge before R2 lands** (same stack). (blocks merge of unit 5)
- [x] R3 backend (backend-4, branch `mig/WP-0b-ports-secrets-pins-backend`, done): split the JWT key (`web/server/configuration/flask.py:34`). `SECRET_KEY = getenv('SECRET_KEY', settings.DEFAULT_SECRET_KEY)`; `JWT_SECRET_KEY = getenv('JWT_SECRET_KEY')`; raise at startup if `JWT_SECRET_KEY` is empty, `changeme`, or equal to `SECRET_KEY`. Compose already passes a required `JWT_SECRET_KEY` to web and worker (unit 4). Existing `accessKey` cookies and API tokens become invalid once, so users sign in again; say so in the release note. SEC-3. (blocks WP close)
- [x] R4 data-platform: done by data-platform-1 on `mig/WP-0b-ports-secrets-pins-druid` (units R4.1 to R4.5 below). Druid setup items from phase 0b, all in `druid_setup/**`:
  - replace `FoolishPassword` (`single/docker-compose.yml:59`, `single/environment/common.env:25`, `cluster/cluster.env:8`) with a required variable (`${DRUID_POSTGRES_PASSWORD:?...}` in Compose, and read it from the env in `common.env`);
  - stop publishing ZooKeeper 2181, memcached 11211 and Postgres (5431/5432) in `single/docker-compose.yml` and `cluster/docker-compose-master.yml`; bind to `127.0.0.1` where a host tool needs them, or to a private interface variable where another host does (cluster mode);
  - pin `postgres:latest` and `memcached` by tag and digest (current: `postgres:15.19-alpine@sha256:f7d23353e1b15400d22ebe31189f4d314b87a4c129cc400c8c2d8d4ca127bf81`; check the major matches the existing metadata volume before choosing), and `zookeeper:${ZOOKEEPER_VERSION}` / `apache/druid:${DRUID_VERSION}` defaults by digest;
  - pin the extension downloads in `extensions/load_extensions.sh:26-35` (they fetch `raw/master` from GitHub) to a commit or tag and verify each with `sha256sum -c`.
  (blocks WP close, not a unit)
- [ ] R5 human: MinIO no longer publishes server images. `minio/minio` on Docker Hub returns "repository does not exist" and `quay.io/minio/minio` returns 401, so `docker-compose.minio.yaml` cannot be pinned or even pulled on a fresh host. Existing hosts keep their cached image. Choose a replacement (a maintained fork image, a source build we publish to `ghcr.io/zenysis`, or another S3-compatible store such as Garage or SeaweedFS). Unit 6 leaves the `minio/minio:latest` line as is until you decide. (does not block other units)
- [ ] R6 human: `.env.example` is infra-owned but agent settings deny reading it (it matches `.env*`). Add `DEFAULT_SECRET_KEY=`, `JWT_SECRET_KEY=`, `REDIS_PASSWORD=` (all generated with `openssl rand -hex 32`), and for separate-host setups `POSTGRES_BIND_ADDRESS=` and `MINIO_BIND_ADDRESS=`, and remove any `changeme` value. Also delete the unused `POSTGRES_DB_URI` entry (nothing reads it, see unit 2). Also update the README production `.env` sample (human-owned) with the same keys. (blocks WP close)
- [ ] R7 backend (WP-0a): the Hasura port 8088 and image upgrade stay with WP-0a. When WP-0a asks, infra edits the `hasura` service; until then this WP leaves that service alone, so `docker compose config` on this branch still shows 8088 published.
  - infra-0a-support (branch `mig/WP-0a-lock-down-hasura-infra`, 7cb07b5) makes `HASURA_ADMIN_SECRET` required and pins Hasura v2.45.8. A trial merge of the two branches is clean, but whichever lands second must edit `tests/infra/test_compose.py`: add `'HASURA_ADMIN_SECRET': 'test-hasura-admin-secret'` to `BASE_ENV`, set `PUBLISHED_UNTIL_WP_0A = set()`, and drop `'hasura'` from `UNPINNED_UNTIL_DECIDED`. Without those edits 12 tests fail because the config does not render. Re-checked by infra-0a-support against WP-0b head 0ecd19e: `docker-compose.yaml` merges cleanly; the only conflict is add/add in `.claude/agent-memory/harmony-infra-engineer/MEMORY.md`, resolved by keeping both index lines; on the merged tree the suites give 12 failed / 44 passed without the R7 edits and 56 passed with them.
- [x] R8 infra (from backend-4, done in unit 10): in `docker-compose.yaml`, give `worker` `REDIS_HOST=redis` in place of the hand-built `BROKER_URL=redis://:${REDIS_PASSWORD}@redis:6379/0`. `get_broker_url` then builds the URL and URL-encodes the password, so the "must be URL-safe" note on the `redis` service can go, and the worker's Flask app cache gets the host and password too (today it has neither). Update `test_redis_requires_auth_and_clients_carry_the_password` to match. Not urgent: with a hex password the current line works. (does not block)

## Log

- 2026-10-04 infra-1 unit 1: claimed WP-0b; check: commit 4acd856.
- 2026-10-04 infra-1 unit 2: `POSTGRES_DB_URI:=` becomes `POSTGRES_DB_URI=` in `docker-compose.pipeline.yaml` (handed over from WP-0c); check: `uv run --no-project --with pytest pytest tests/infra` failed before (env key was `POSTGRES_DB_URI:`), 1 passed after.
- 2026-10-04 infra-1 unit 3: base file publishes only nginx (redis, web, worker ports removed); dev binds postgres, redis, web to 127.0.0.1; db/minio files require an explicit bind address; check: `pytest tests/infra` 6 new tests failed before, 7 passed after; port summary under Evidence.
- 2026-10-04 infra-1 unit 4: `:-changeme` fallbacks removed; `DEFAULT_SECRET_KEY`, `JWT_SECRET_KEY` (web, worker), `POSTGRES_PASSWORD`, `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` are `${VAR:?message}`; check: `pytest tests/infra` 14 new cases failed before, 27 passed after.
- 2026-10-04 infra-1 unit 5: Redis runs with `--requirepass ${REDIS_PASSWORD:?}`; `REDISCLI_AUTH` for the healthcheck, which now matches `PONG`; web and worker get `REDIS_PASSWORD`, worker `BROKER_URL` carries it; check: `pytest tests/infra` 3 new cases failed before, 30 passed after; throwaway Redis rejects unauthenticated clients (Evidence). Merge-blocked on R2.
- 2026-10-04 infra-1 unit 6: nginx-proxy, acme-companion, redis and postgres pinned by version tag and digest; check: `pytest tests/infra` pin test failed for 3 file sets before, 34 passed after; each tag re-resolved to its digest with `docker buildx imagetools inspect`.
- 2026-10-04 infra-1 unit 7: Dockerfile bases pinned by digest (python, node, ubuntu); mc moved to its pinned GitHub release (dl.minio.io returns 410) and verified with sha256sum; flow, pypy and CPython verified by checksum; check: `docker build --check` (no new warnings), dev and pipeline `downloader` stages built with every checksum OK, web-server image built (Evidence).
- 2026-10-04 infra-1 unit 8: dev overlay runtime check; check: postgres 15.19 and redis 8.10.2 healthy, published on 127.0.0.1 only, Redis refuses unauthenticated clients from the host; torn down.
- 2026-10-04 infra-1 unit 2 (revised on lead request after WP-0c interrogate): the `POSTGRES_DB_URI` line and its "Alembic uses" comment are deleted rather than corrected; the test now asserts the key is absent, and a new test asserts no `environment:` key contains `:` in any Compose file set; check: absence test failed against the corrected line, 39 passed after; the colon check flags `POSTGRES_DB_URI:` when run against main's file.
- 2026-10-04 infra-1 unit 9: `bcrypt==4.0.1` pinned beside `flask-user` in `requirements.txt` (WP-0a finding: the unpinned resolve gave bcrypt 5.0.0, which breaks passlib 1.7.4); check: `tests/infra/test_requirements.py` failed before, 40 passed after; web-server image rebuilt and hashes a password. Port 5000 (also from WP-0a) was already closed in unit 3; no change.
- 2026-10-04 infra-1 merge: `mig/WP-0b-ports-secrets-pins-backend` (629734b, which carries core-3's R1) merged; WP-file conflict resolved keeping every tick, log line and evidence section; check: `tests/web` + `tests/infra` on Python 3.8 59 passed, `tests/core` + `tests/infra` 47 passed.
- 2026-10-04 infra-1 unit 10 (R8): worker gets `REDIS_HOST=redis` in place of `BROKER_URL=redis://:<pw>@redis:6379/0`; check: updated test failed (`KeyError: 'REDIS_HOST'`) before, 40 passed after; with the worker's env and the password `p@ss:w/rd%#?&= x`, `CeleryConfig.broker_url` parses back to host `redis`, port 6379, the exact password and db 0 (the same db as before).
- 2026-10-04 infra-1 merge: `mig/WP-0b-ports-secrets-pins-druid` (6c6d61a, R4) merged; WP-file conflicts resolved keeping every tick, log line, evidence section, deployment note and deferral; added the `postgres:latest` = 18 finding to the Druid deployment notes and the Druid HTTP ports to "For the security reviewer"; check: `tests/core` + `tests/infra` + `tests/druid_setup` 69 passed; `tests/web` + `tests/infra` + `tests/druid_setup` on Python 3.8 81 passed.
- 2026-10-04 core-3 R1: `config/settings.py` refuses an unset, blank or `changeme` (case-insensitive, stripped) `DEFAULT_SECRET_KEY` at import with a `RuntimeError` naming the variable and `openssl rand -hex 32`; a real key passes through unchanged. Kept at import, not at the Flask read, because pipeline validate steps (`fetch_fields_from_database.py`, `update_db_datasource.py`) build a Flask app, so a lazy check would fail after indexing; no importer ran without the key before (it was `os.environ[...]`). Check: `uv run --no-project --with pytest pytest tests/core` 6 failed before, 7 passed after.
- 2026-10-04 backend-4 R2: `get_broker_url` and the Flask Redis cache send `REDIS_PASSWORD` (URL-encoded in the broker URL, passed as `CACHE_REDIS_PASSWORD` to the cache); both refuse to start with a `RuntimeError` naming `REDIS_PASSWORD` when `REDIS_HOST` is set and the password is unset or empty; an explicit `BROKER_URL` and the no-Redis default are unchanged; check: `pytest tests/web/test_redis_password.py` 6 failed before, 9 passed after; Celery broker, result backend and Flask cache authenticated against a throwaway `redis:8.10.2` with password `p@ss:w/rd%#?&= x` (Evidence).
- 2026-10-04 backend-4 R3: `JWT_SECRET_KEY` split from the session key. `FlaskConfiguration.SECRET_KEY` is `settings.DEFAULT_SECRET_KEY` only (the unchecked `SECRET_KEY` env override is gone, per core-3's note on R1). `initialize_jwt_manager` reads `JWT_SECRET_KEY` through `settings.require_secret` and refuses one equal to the session key, then sets it before `JWTManager(app)`; web calls it first in startup, before the database and Druid steps; the worker already calls it. Pipeline scripts build a `FlaskConfiguration` but never reach it, so the pipeline needs no JWT key. The request loader now treats a bad-signature token (an old cookie or API token) as anonymous, as it already did for an expired one; without that, every request carrying an old `accessKey` cookie failed with flask-jwt-extended's 422 "Signature verification failed", `/login` included; check: `pytest tests/web/test_jwt_secret_key.py` 9 failed before (8 for the split, 1 for the old cookie), 10 passed after; `create_app` under `SERVER_SOFTWARE=gunicorn` refuses unset, `ChangeMe` and equal keys and gets past the check with a valid one (Evidence).
- 2026-10-04 data-platform-1 R4.1: `FoolishPassword` removed from `druid_setup`; Compose requires `DRUID_POSTGRES_PASSWORD` (`${VAR:?}`) for postgres and the coordinator, Druid reads it through the `environment` password provider (in 0.23: `core/.../PasswordProvider.java` registers `environment`), the Makefile exports it from `druid_setup/.env`; check: `pytest tests/druid_setup` 9 failed before, 9 passed after.
- 2026-10-04 data-platform-1 R4.2: single mode publishes no ZooKeeper, memcached or Postgres port; cluster master drops memcached and binds ZooKeeper and Postgres to `${DRUID_MASTER_HOST}`; check: port test failed for single and master before, 13 passed after; port summary under Evidence.
- 2026-10-04 data-platform-1 R4.3: Druid 0.23.0, ZooKeeper 3.8.6, memcached 1.6.45 and Postgres 17.11-bookworm pinned by tag and digest; `DRUID_POSTGRES_IMAGE` selects a pinned 14/15/16 image for hosts whose metadata volume predates 17; `ZOOKEEPER_VERSION` removed; check: pin test failed for all four files before, 17 passed after; every tag re-resolved with `docker buildx imagetools inspect`.
- 2026-10-04 data-platform-1 R4.4: extension jars pinned to commit URLs with a SHA-256 table in `load_extensions.sh`, verified with `sha256sum -c` in a staging directory before the volume is replaced; loader base `alpine:3.24.2@sha256`; `DRUID_VERSION`/`ZEN_DRUID_VERSION` removed (the table names the version, a test ties it to the Druid image tag); check: 2 extension tests failed before, 22 passed after; loader built and run (Evidence).
- 2026-10-04 data-platform-1 R4.5: single-server runtime check on throwaway project `wp0b-druid-check`; check: pinned images up, coordinator authenticated to Postgres 17.11 through the password provider, an inline `index_parallel` task published a segment (peon without the password variable), password absent from container logs; torn down without `-v`.
- 2026-10-04 data-platform-1 R4.6 (sec-0b HIGH): no Druid port is published on every interface. Single mode drops historical 8083 and middlemanager 8091/8100-8105 and binds coordinator, broker and router to a required `DRUID_BIND_ADDRESS`, which the Makefile exports. Cluster master, data and query bind to `DRUID_MASTER_HOST`, `DRUID_DATA_HOST` and the new `DRUID_QUERY_HOST`. Check: `pytest tests/druid_setup` 11 failed before (wildcard publication, exact port set per file, required bind variable), 30 passed after.

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

### Unit 4: secrets refused at the Compose layer

`docker compose -f docker-compose.yaml config -q` with no `DEFAULT_SECRET_KEY` / `JWT_SECRET_KEY` (exit 1, before any container is touched):

```
error while interpolating services.web.environment.[]: required variable DEFAULT_SECRET_KEY is missing a value: set DEFAULT_SECRET_KEY to a random value, e.g. openssl rand -hex 32
error while interpolating services.web.environment.[]: required variable JWT_SECRET_KEY is missing a value: set JWT_SECRET_KEY to a random value different from DEFAULT_SECRET_KEY, e.g. openssl rand -hex 32
error while interpolating services.worker.environment.[]: required variable DEFAULT_SECRET_KEY is missing a value: ...
error while interpolating services.worker.environment.[]: required variable JWT_SECRET_KEY is missing a value: ...
exit=1
```

`tests/infra/test_compose.py::test_refuses_to_render_without_secret` covers unset and empty values for every required secret in every Compose file (14 cases); `test_no_default_secret_in_rendered_config` asserts `changeme` appears in no rendered file. An explicit `DEFAULT_SECRET_KEY=changeme` still renders; R1 makes the process refuse it.

### Unit 5: Redis `requirepass`

Throwaway project `wp0b-redis-check`, the base file's `redis` service plus an overlay that resets its volume (no data written), random test password:

```
up -d --wait redis                       -> Healthy
redis-cli ping (no password)             -> NOAUTH Authentication required.
redis-cli ping (wrong password)          -> WRONGPASS invalid username-password pair
redis-cli ping (REDISCLI_AUTH from env)  -> PONG
redis-cli -u redis://:<pw>@localhost:6379/0 ping (worker BROKER_URL form) -> PONG
ps -o user,args                          -> redis    redis-server *:6379   (password not in the process title; runs as the redis user)
healthcheck with wrong password          -> exit 1 (old `redis-cli incr ping` exited 0 on NOAUTH, so it could not detect a bad password)
down                                     -> container and network removed, no volumes created
```

Not yet exercised: the web container against the password-protected Redis. That needs R2 and a built web image; QA should run it once R2 lands.

### Unit 6: Compose images pinned (`docker buildx imagetools inspect <tag>`, 2026-10-04)

| Before | After | Note |
|---|---|---|
| `nginxproxy/nginx-proxy:alpine` | `1.11.6-alpine@sha256:99376e95…c03364` | latest release |
| `nginxproxy/acme-companion` (no tag) | `2.8.2@sha256:e3c5fb08…6f34cbc1` | latest release; `latest` points at a newer untagged build |
| `redis:alpine` | `8.10.2-alpine@sha256:38117873…0a0e5a0` | same digest `redis:alpine` resolves to today, so no RDB downgrade for hosts that pulled recently. A host still on Redis 7 upgrades in place (8 reads 7's RDB) |
| `postgres:15.2-alpine` (dev, db) | `15.19-alpine@sha256:f7d23353…127bf81` | minor upgrade within 15: same on-disk format, no dump/restore; picks up 17 minor releases of fixes |
| `hasura/graphql-engine:v2.11.3…` | unchanged | WP-0a upgrades and pins it |
| `minio/minio:latest` | unchanged | image no longer published anywhere (R5) |

Each tag resolved to the pinned digest at the time of writing. `test_third_party_images_are_pinned_by_digest` fails if a new third-party image arrives without a version tag and digest.

### Unit 7: Dockerfile bases and downloads

Base images (each digest equals what the floating tag resolved to on 2026-10-04, so the bytes do not change):

| Dockerfile | Before | After |
|---|---|---|
| `docker/web/Dockerfile_web-server` | `python:3.8` | `python:3.8.20-bookworm@sha256:d4112707…070e390c` |
| `docker/web/Dockerfile_web-client` | `node:18.17` | `node:18.17.1-bookworm@sha256:933bcfad…7b23c24` |
| `docker/pipeline/Dockerfile`, `docker/dev/Dockerfile` (2 stages each) | `ubuntu:22.04` | `ubuntu:jammy-20260924.1@sha256:5ec03bb3…6486401` |

Downloads:

| Artefact | Checksum source |
|---|---|
| `mc` RELEASE.2025-08-13T08-35-41Z, amd64 and arm64 (pipeline, dev) | the release's own `.sha256sum` files and GitHub's asset digests agree with my download |
| flow v0.200.0, linux64 and linux-arm64 (dev) | no published digest; computed from the GitHub release asset (trust on first use) |
| pypy3.9 v7.3.11, linux64 and aarch64 (dev) | match pypy.org/checksums.html |
| CPython 3.9.16 tarball (dev, `ADD --checksum`) | GPG signature verified: "Good signature from Łukasz Langa", key E3FF 2839 C048 B25C 084D EBE9 B269 95E3 1025 0568 |

Found on the way: `https://dl.minio.io/client/mc/release/...` now returns **410 Gone**, so the pipeline and dev images could not be built from `main`. The pinned GitHub release fixes that. The `minio/mc` repository is archived; mc needs a successor along with the server (R5).

Checks:
- `docker build --check` on the pipeline and dev Dockerfiles: before 1 `FromAsCasing` plus 6 and 2 `LegacyKeyValueFormat`; after 0 `FromAsCasing`, same `LegacyKeyValueFormat` (pre-existing, WP-3b rewrites these files). web-server and web-client: 1 pre-existing warning each.
- `docker build --target downloader -f docker/dev/Dockerfile .`: `/usr/local/bin/mc: OK`, `/tmp/flow.zip: OK`, `/tmp/pypy.tar.bz2: OK`; mc, flow and pypy present in the stage.
- `docker build --target downloader -f docker/pipeline/Dockerfile .`: `/usr/local/bin/mc: OK`.
- `ADD --checksum` line in a scratch Dockerfile: correct digest builds; one changed hex digit fails with `digest mismatch`.
- `docker build -f docker/web/Dockerfile_web-server .`: exit 0; image runs Python 3.8.20, flask 1.0.1, celery 5.4.0, redis-py 5.0.1.
- Not built: the full dev and pipeline images (their apt and pip layers do not touch the pins) and web-client (digest equals today's `node:18.17`).

### Unit 8: dev-overlay runtime check

Throwaway project `wp0b-dev-check`: `docker-compose.yaml` + `docker-compose.dev.yaml` + an overlay that moves the host ports to 15432/16379 (this host already runs Postgres and Redis on 5432/6379) and drops the named volumes.

```
postgres  postgres:15.19-alpine@sha256:f7d23353…  Up (healthy)  127.0.0.1:15432->5432/tcp
redis     redis:8.10.2-alpine@sha256:38117873…    Up (healthy)  127.0.0.1:16379->6379/tcp
select version()                      -> PostgreSQL 15.19 on x86_64-pc-linux-musl
redis-cli -h 127.0.0.1 -p 16379 ping  -> NOAUTH Authentication required.
down                                  -> containers and network removed
```

Not run: `make up DEV=1` with web and the pipeline. The dev image takes a long time to build (it compiles CPython), web needs a reachable Druid, and web against the password-protected Redis needs R2. QA should run the full `make up DEV=1` plus the smoke list once R1 to R3 land.

### Unit 9: bcrypt pin

`bcrypt` came in unpinned through `flask-user`, and the web image built on 2026-10-04 resolved **bcrypt 5.0.0**. In that image, passlib's bcrypt self-test raises `ValueError: password cannot be longer than 72 bytes` on the first hash, so `scripts/create_user.py` and every Flask-User password hash fail.

passlib 1.7.4 hash plus verify on Python 3.8, by bcrypt version (`uv run --with passlib==1.7.4 --with bcrypt==X`):

| bcrypt | result |
|---|---|
| 4.0.1 | works |
| 4.1.3, 4.3.0 | works, but passlib logs `(trapped) error reading bcrypt version` because `bcrypt.__about__` is gone |
| 5.0.0 | `ValueError` on first hash |

So the hard break is 5.0, and 4.1 to 4.3 only add log noise. Following the lead, the pin is the last 4.0.x (4.0.1), which needs neither workaround. It goes in `requirements.txt` beside `flask-user`, with the same PyPy marker, rather than in `requirements-web.txt`: the pipeline and dev images install `requirements.txt` without `requirements-web.txt` and also get flask-user.

Checks: `test_passlib_can_hash_with_the_installed_bcrypt` failed with "bcrypt is not pinned" before the pin and passes after; full `tests/infra` 40 passed. `docker build -f docker/web/Dockerfile_web-server .` exit 0; inside the image: `bcrypt 4.0.1 hash+verify True` (the previous build had bcrypt 5.0.0 and raised `ValueError`).

### Port 5000 (WP-0a finding)

WP-0a reported that the base file publishes `web` on 5000. That was true on `main`; unit 3 (commit 42adab6) already removed it. The dev overlay binds `127.0.0.1:5000`, and `test_only_nginx_publishes_ports` (base, prod, local) and `test_dev_publishes_on_loopback_only` cover it. No further change.

### R2 and R3 (backend-4)

Test environment: Python 3.8 with `requirements.txt` and `requirements-web.txt`, as described in WP-0c's "How to run the tests" (the requirements rewritten into `/tmp/reqs.txt`):

```
PYTHONPATH=$PWD uv run --no-project -p 3.8 --with-requirements /tmp/reqs.txt --with 'pytest<8' \
  python -m pytest tests/web tests/infra -q -p no:cacheprovider -W ignore      -> 58 passed
uv run --no-project --with pytest pytest tests/core -q                        -> 7 passed
pylint 2.17.4 (.pylintrc) and black 22.6.0 --skip-string-normalization on the changed files -> 10.00/10, unchanged
```

Before the fixes: `tests/web/test_redis_password.py` 6 failed, 3 passed; `tests/web/test_jwt_secret_key.py` 9 failed, 1 passed.

R2 against a throwaway `redis:8.10.2-alpine` (the pinned digest), `--requirepass 'p@ss:w/rd%#?&= x'`, on `127.0.0.1:16379` (the host already uses 6379, so the check script sets the port to 16379). Container removed afterwards:

```
celery broker connected: redis://:**@127.0.0.1:16379//
celery result backend uri (as logged): redis://:**@127.0.0.1:16379/
celery result backend ping: True
flask cache round trip: ok
no password: AuthenticationError Authentication required.
```

Celery 5.4.0 masks the password in the URIs it logs (`as_uri()` above).

Startup checks (dummy values, no `.env`):

```
REDIS_HOST=redis, no REDIS_PASSWORD, import web.server.configuration.celery
  RuntimeError: REDIS_PASSWORD is unset or empty but REDIS_HOST is set; refusing to start. ...
REDIS_HOST and JWT_SECRET_KEY unset (pipeline-like): FlaskConfiguration() and celery config import fine
create_app() with SERVER_SOFTWARE=gunicorn/20:
  JWT_SECRET_KEY unset     -> RuntimeError: JWT_SECRET_KEY is unset, empty or the default "changeme"; refusing to start. ...
  JWT_SECRET_KEY=ChangeMe  -> same
  JWT_SECRET_KEY=DEFAULT_SECRET_KEY -> RuntimeError: JWT_SECRET_KEY equals DEFAULT_SECRET_KEY; refusing to start. ...
  JWT_SECRET_KEY valid     -> passes the check, then stops at the database step (no database in this check)
docker compose --env-file /dev/null -f docker-compose.yaml -f docker-compose.dev.yaml config -q -> exit 0
  web:    REDIS_HOST=redis, REDIS_PASSWORD, DEFAULT_SECRET_KEY, JWT_SECRET_KEY
  worker: BROKER_URL=redis://:<pw>@redis:6379/0, REDIS_PASSWORD, DEFAULT_SECRET_KEY, JWT_SECRET_KEY
```

Not run: web and worker containers against the password-protected Redis, and a browser carrying an old `accessKey` cookie through `/login`. Both need a built image and a database; QA should include them in the `make up DEV=1` smoke run.

### R4: Druid setup (data-platform-1)

Tests: `uv run --no-project --with pytest pytest tests/druid_setup` gives 22 passed (`test_druid_compose.py` renders all four Druid Compose files with dummy values and a scrubbed environment; `test_druid_extensions.py` parses `load_extensions.sh`). Together with `tests/infra`: 56 passed.

Missing password, single mode (`docker compose --env-file environment/common.env config -q`, exit 1):

```
error while interpolating services.coordinator.environment.[]: required variable DRUID_POSTGRES_PASSWORD is missing a value: set DRUID_POSTGRES_PASSWORD in druid_setup/.env to a random value, e.g. openssl rand -hex 32
error while interpolating services.postgres.environment.[]: required variable DRUID_POSTGRES_PASSWORD is missing a value: ...
```

Published ports (`docker compose config`, dummy env):

```
## single/docker-compose.yml        (before: also postgres 0.0.0.0:5431, memcache 0.0.0.0:11211, zookeeper 0.0.0.0:2181)
broker 0.0.0.0:8082, coordinator 0.0.0.0:8081, historical 0.0.0.0:8083,
middlemanager 0.0.0.0:8091 + 8100-8105, router 0.0.0.0:8888
## cluster/docker-compose-master.yml (before: postgres 0.0.0.0:5432, memcache 0.0.0.0:11211, zookeeper 0.0.0.0:2181)
coordinator 0.0.0.0:8081, postgres 10.0.0.10:5432, zookeeper 10.0.0.10:2181   (10.0.0.10 = DRUID_MASTER_HOST)
```

Images (each tag re-resolved with `docker buildx imagetools inspect` on 2026-10-04; each equals what the floating tag resolves to today):

| Before | After |
|---|---|
| `postgres:latest` | `postgres:17.11-bookworm@sha256:639ab7ce…b534b652`, overridable with `DRUID_POSTGRES_IMAGE` (pinned 16.15, 15.19, 14.24 refs in the Compose comment) |
| `memcached` | `memcached:1.6.45@sha256:405a445c…e6482be4ad` |
| `zookeeper:${ZOOKEEPER_VERSION}` (3.8) | `zookeeper:3.8.6@sha256:6abd40b4…e284214e` |
| `apache/druid:${DRUID_VERSION}` (0.23.0) | `apache/druid:0.23.0@sha256:ed971996…f65912` |
| extension loader `alpine:latest` | `alpine:3.24.2@sha256:294b683c…eaec77e6` |

Extension downloads (`raw/master` before, commit URLs after). The Zenysis repositories have no tags or releases. For each jar, the pinned commit and `raw/master` served the same bytes today, and git history shows each 0.23.0 jar unchanged since August 2022, so hosts already have these bytes. druid-datasketches matches the `.sha1` the Apache repository publishes (`46b2daac…`). Maven Central did not resolve from this host, so it was not cross-checked there.

Extension loader, built and run into throwaway volume `wp0b-druid-ext-check`:

```
druid-aggregatable-first-last-0.23.0.jar: OK
druid-arbitrary-granularity-0.23.0.jar: OK
druid-nested-json-parser-0.23.0.jar: OK
druid-tuple-sketch-expansion-0.23.0.jar: OK
druid-datasketches-0.23.0.jar: OK                 exit 0, same directory layout as before
one hex digit changed in the table -> FAILED, "1 of 1 computed checksums did NOT match", exit 1; the jars already in the volume stay in place
```

Runtime check (throwaway project `wp0b-druid-check`: postgres, zookeeper, memcache, extension_loader, coordinator, middlemanager; an overlay moved the coordinator to `127.0.0.1:18081` and removed the middlemanager ports because this host already uses 8081, 8082 and 8888):

```
images              all running from the pinned digests above
postgres            5432/tcp (not published); memcache 11211/tcp; zookeeper 2181/tcp
coordinator logs    "druid.metadata.storage.connector.password: <masked>", the provider JSON in runtime.properties, 0 hits for the password, 0 PSQLException
metadata tables     druid_audit … druid_tasks created by the coordinator
inline index_parallel task      SUCCESS; druid_segments has wp0b_check 2026-09-01 used=t
middlemanager       no DRUID_POSTGRES_PASSWORD variable; peons publish through the overlord
down                containers and network removed, volumes kept (see Leftovers)
```

`postgres:18.6` with the existing `/var/lib/postgresql/data` mount refuses to start ("The suggested container configuration for 18+ is to place a single mount at /var/lib/postgresql…"). `postgres:latest` has resolved to 18 since late 2025, so on `main` a fresh Druid host cannot start its metadata store, and an existing host breaks the next time it pulls.

## For the security reviewer

- **Auth behaviour change (backend-4, R3):** `login_from_request` now treats a JWT with a bad signature as anonymous, as it already did for an expired one, instead of letting flask-jwt-extended return 422 "Signature verification failed". Without this, every request carrying a pre-upgrade `accessKey` cookie failed, including `/login`. Please confirm that a forged or tampered token can never authenticate this way: it must fall through to the anonymous path, with no partial identity. Test: `tests/web/test_jwt_secret_key.py`.
- `SECRET_KEY` from the environment no longer overrides the checked `DEFAULT_SECRET_KEY`.
- Web and worker refuse to start with an unset or empty `REDIS_PASSWORD` when `REDIS_HOST` is set, and with a `JWT_SECRET_KEY` that is unset, `changeme` or equal to the session key.
- Druid's own HTTP ports (sec-0b HIGH, fixed in R4.6): single mode publishes only the coordinator, broker and router, on a required `DRUID_BIND_ADDRESS`. Historical and middlemanager are no longer published. In cluster mode, each host binds its ports to its own private address. No Druid port is published on every interface; `tests/druid_setup` fails if one is. Druid still has no authenticator, so the firewall rule in the deployment notes carries the rest. The lead plans Druid authentication for WP-8a/8b.
- Druid's metadata password is now read from the environment rather than the Druid config, so it never reaches the Docker logs (R4).

## Deployment notes (operator action at upgrade)

Druid hosts (R4):
- `druid_setup` on `main` already fails today: `postgres:latest` has resolved to 18 since late 2025, and 18 refuses the existing `/var/lib/postgresql/data` mount. A fresh Druid host cannot start its metadata store, and an existing host breaks the next time it pulls. WP-0b pins Postgres 17.11, with `DRUID_POSTGRES_IMAGE` for hosts on 14, 15 or 16 (next bullet).
- Before upgrading, read the metadata store's major: `docker compose -p druid exec postgres cat /var/lib/postgresql/data/PG_VERSION`. If it is not 17, set `DRUID_POSTGRES_IMAGE` in `druid_setup/.env` to the matching pinned line in the Compose comment. Otherwise Postgres refuses to start. It does not touch the data.
- Set `DRUID_POSTGRES_PASSWORD` in `druid_setup/.env` (hex, e.g. `openssl rand -hex 32`; the Makefile `include`s that file, so `$` would be expanded). The Postgres image applies its password only when it creates a volume. On an existing host, first run `docker compose -p druid exec postgres psql -U druid -d druid -c "ALTER USER druid WITH PASSWORD '<new>'"`, then `make single_server_up` (or the cluster target). Setting `DRUID_POSTGRES_PASSWORD=FoolishPassword` also works but keeps the known password.
- Anything that used host ports 5431 (single Postgres), 2181 or 11211 has to use `docker compose exec` now. In cluster mode, ZooKeeper and Postgres listen on `DRUID_MASTER_HOST` only. That address must be the one data and query hosts use for `DRUID_ZOOKEEPER_HOST`, and the one the coordinator uses for `DRUID_POSTGRES_HOST`.
- Druid's HTTP ports are no longer published on every interface (R4.6). Druid has no authentication, so **firewall these ports so only the web and pipeline hosts (and, in cluster mode, the other Druid hosts) can reach them**. The lead plans Druid authentication for WP-8a/8b.
  - Single mode: set `DRUID_BIND_ADDRESS` in `druid_setup/.env` to the address web and the pipeline use in `DRUID_HOST`. That is the host's private IP when web is on another host or in a container. Use `127.0.0.1` only if every client runs on this host outside Docker's bridge network. The coordinator (8081), broker (8082) and router (8888) listen there. Historical (8083) and middlemanager (8091, 8100-8105) are internal now.
  - Cluster mode: set `DRUID_QUERY_HOST` in `cluster.env` alongside `DRUID_MASTER_HOST` and `DRUID_DATA_HOST`. Each file binds its ports to its host's address: master 8081, 2181, 5432; data 8083, 8091, 8100-8105; query 8082, 8888.
- `DRUID_VERSION` and `ZOOKEEPER_VERSION` are gone from the env files. The versions live in the Compose image references and in the checksum table in `load_extensions.sh`.

Web hosts:
- Set `DEFAULT_SECRET_KEY`, `JWT_SECRET_KEY` (different values) and `REDIS_PASSWORD` in the web host's `.env`, generated with `openssl rand -hex 32`. Until they are set, `make up` stops at config time and leaves running containers untouched.
- The README's production `.env` sample never listed `DEFAULT_SECRET_KEY`, so most deployments run on `changeme`. Setting a real key, and the JWT split (R3), signs every user out once.
- After the JWT split (R3), every `accessKey` cookie and every API token issued before the upgrade stops verifying. Users are sent to the login page once and sign in again; nothing needs clearing in the browser. **API tokens must be reissued**: they are 20-year JWTs signed with the old key, used by `web/python_client` and integrations. Tell token holders before the upgrade, and revoke the old tokens afterwards.
- `SECRET_KEY` in the environment no longer overrides `DEFAULT_SECRET_KEY` (it bypassed the R1 check). Compose never passed it; a host that set it outside Compose must move the value to `DEFAULT_SECRET_KEY`.
- Web and worker refuse to start when `REDIS_HOST` is set without `REDIS_PASSWORD`. Compose sets both.
- Separate Postgres host (`docker-compose.db.yaml`): set `POSTGRES_BIND_ADDRESS` to the private interface IP, or to `127.0.0.1` when web shares the host. The same applies to `MINIO_BIND_ADDRESS`.
- Anything that reached web on host port 5000, Redis on 6379 or the worker on 61234 directly now has to go through nginx, or through `127.0.0.1` in dev.
- Postgres moves from 15.2 to 15.19 (minor upgrade, no dump or restore) and Redis is pinned to 8.10.2.

## Deferrals

- `curl https://deb.nodesource.com/setup_14.x | bash` in `docker/dev/Dockerfile` stays unpinned. WP-6b replaces Node 14 with Node 24 and deletes it (FE-11).
- Python requirements are not hash-locked. WP-2f moves them to `uv.lock`.
- `bcrypt==4.0.1` is held back for passlib 1.7.4 (unit 9). Lift it when passlib goes: WP-3d (Flask 2.3 upgrade) or WP-5d, which retires Flask-User. Keep `tests/infra/test_requirements.py` or replace it with an equivalent hashing test.
- deadsnakes PPA and apt packages in the pipeline and dev images are not version-pinned. WP-3b rewrites these images.
- The dev overlay keeps its fixed `postgres`/`zenysis` credentials with `trust` auth. They are dev-only, bound to loopback, and the dev web and pipeline hard-code the same URL.
- Hasura (port 8088 and image) is WP-0a's (R7). MinIO server image and `mc` successor: R5.
- Druid has no authenticator, and `druid_javascript_enabled=true`. Since R4.6 its ports are bound to one address per host and must be firewalled (see Deployment notes). The lead plans Druid authentication for WP-8a/8b, and WP-8a disables JavaScript.
- Cluster mode: Postgres stays published on `DRUID_MASTER_HOST` because the coordinator reaches it through `DRUID_POSTGRES_HOST`. WP-8b, which rewrites the cluster files for ZooKeeper removal, should point the coordinator at the `postgres` service and drop the port.
- The loader's `apk add bash` is not version-pinned; the base image digest is.
- Phase 0b cites `load_extensions.sh:286`; the file had 35 lines, and the downloads were at lines 26-35.

## Leftovers on the build host

- Test images `wp0b-web-server:check` (2.4 GB), `wp0b-pipeline-downloader:check` and `wp0b-dev-downloader:check`, kept so reviewers can inspect them. Remove with `docker rmi` when done.
- The throwaway projects were torn down with `docker compose down` (no `-v`). Postgres and Redis declare `VOLUME`, so a few anonymous volumes may remain (for example `385c87b4…`, created 2026-10-04 17:32). The host also holds anonymous volumes from other agents, so I did not remove any.
- data-platform-1 (R4): image `wp0b-druid-extensions:check` and project image `wp0b-druid-check-extension_loader`; volumes `wp0b-druid-ext-check` and `wp0b-druid-check_{coordinator_var,metadata_data,middle_var,zen_extensions,zookeeper_data,zookeeper_datalog,zookeeper_logs}` (test data only); scratch dirs `/tmp/dp1_druid`. Remove with `docker rmi` and `docker volume rm` when the review is done.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | changes-requested | 2026-10-04 qa-0b at c03a86d: 69 and 81 tests pass, fail-before confirmed, ports, digests, checksums, Redis auth, web and worker up on authenticated Redis with a special-character password, JWT split verified. Fix: the Celery worker swallows the SEC-3 refusal (pool children log RuntimeError but the worker reports ready); deployment notes omit pipeline hosts (pipeline compose now requires DEFAULT_SECRET_KEY and settings refuse changeme). black wants to reformat tests/druid_setup/test_druid_compose.py:52-53. |
| reviewer | pending | |
| security | changes-requested | 2026-10-04 sec-0b at c03a86d: JWT split, bad-signature-as-anonymous (8 adversarial cases), Redis password never logged, 15 digests re-resolved, checksums fail closed all held. Blocking: Druid HTTP ports (8081-8105, 8888) published on 0.0.0.0 with no auth and JS on: bind to DRUID_BIND_ADDRESS now, unpublish 8083/8091/8100-8105 in single mode, per-host IPs in cluster, test for 0.0.0.0, firewall note; FoolishPassword still accepted and offered by the notes: refuse it in the Makefile. Low: DRUID_POSTGRES_IMAGE override unpinned; dev Dockerfile syntax line floating; JWT_SECRET_KEY minimum 32 chars. |
