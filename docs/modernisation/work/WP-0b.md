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

## Log

- 2026-10-04 infra-1 unit 1: claimed WP-0b; check: commit 4acd856.
- 2026-10-04 infra-1 unit 2: `POSTGRES_DB_URI:=` becomes `POSTGRES_DB_URI=` in `docker-compose.pipeline.yaml` (handed over from WP-0c); check: `uv run --no-project --with pytest pytest tests/infra` failed before (env key was `POSTGRES_DB_URI:`), 1 passed after.

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
