---
wp: "0a"
title: "Lock down Hasura"
status: building
owner_role: "backend"
instances:
  - name: "backend-1"
    files:
      - graphql/hasura/metadata/versions/**
      - web/server/routes/api.py
      - web/server/configuration/flask.py
      - web/server/util/hasura.py
      - scripts/db/hasura/**
      - web/runserver.py
      - tests/web/server/test_hasura_proxy.py
branch: "mig/WP-0a-lock-down-hasura"
requirements: [SEC-1, SEC-2, SEC-9]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0a: Lock down Hasura

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Hasura metadata grants a `user` role exactly the tables and operations the compiled Relay operations use, and an `anonymous` role read access to the tables behind the public-access query. Check: `scripts/db/hasura/check_role_permissions.py` validates every compiled operation in `web/client/**/__generated__` against each role's introspected schema on Hasura v2.11 and v2.45.
2. The Flask proxy sends the admin secret, `x-hasura-role` and `x-hasura-user-id` derived from `current_user`, and refuses to call Hasura without a configured secret. Check: unit tests under `tests/web/`, then the proxy replaying compiled operations against a live Hasura v2.45.
3. `apply_metadata_snapshot.py` takes the secret from the environment, uses `/v1/metadata`, and exits non-zero on failure. Check: run against Hasura v2.45 with and without the secret.
4. Local dev Hasura (`start_hasura.sh`, `runserver.py`) runs v2.45.8 pinned by digest, bound to 127.0.0.1, with an admin secret. Check: script run, `curl` without the secret refused.
5. Compose changes for infra (image pin, no published port, admin secret, env for web) recorded under Requests, verified on a throwaway Compose project. Check: `curl` from the host to Hasura fails; with the secret through the proxy it succeeds.

## Decisions and deviations

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
