---
wp: "0b"
title: "Close published ports, refuse default secrets, pin images"
status: claimed
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

## Contract changes

None.

## Requests

## Log

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
