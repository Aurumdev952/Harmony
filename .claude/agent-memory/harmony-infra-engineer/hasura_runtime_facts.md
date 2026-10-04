---
name: hasura-runtime-facts
description: Hasura v2.45.8 behaviours that matter for Compose checks (status codes, image tools, dev-mode scope) and the WP-0a/WP-0b test-fixture coupling
metadata:
  type: project
---

Hasura `v2.45.8.cli-migrations-v2` facts, observed on 2026-10-04 (WP-0a):

- Without an admin secret, `/v1/graphql` answers **HTTP 200** with `extensions.code: access-denied`. `/v1/metadata` answers **401**. Assert on the error code, not the status, when probing GraphQL.
- With `HASURA_GRAPHQL_DEV_MODE=false`, the admin role still gets `internal` error detail, because `HASURA_GRAPHQL_ADMIN_INTERNAL_ERRORS` defaults to true. Dev mode governs the other roles, `user` and `anonymous`, which are what the Flask proxy sends.
- `/console` returns 404 when `HASURA_GRAPHQL_ENABLE_CONSOLE=false`.
- The image has `curl` and `bash` but no `wget`. `curl -fsS http://127.0.0.1:8080/healthz` works as the healthcheck.
- The cli-migrations entrypoint runs a temporary server on port 9691 with only the metadata API enabled. `hasura-cli` authenticates to it through the `HASURA_GRAPHQL_ADMIN_SECRET` env var.
- `docker compose exec hasura curl ...` is the way to probe in-network, since Hasura publishes no port. Host port 8080 here belongs to an unrelated app (Frappe), so do not probe it from the host.

**Why:** WP-0a made `HASURA_ADMIN_SECRET` required (`:?`) in the base Compose file. Any compose test fixture that renders `docker-compose.yaml` needs it, including WP-0b's `tests/infra/test_compose.py` `BASE_ENV`, which also carries hasura exemptions (`PUBLISHED_UNTIL_WP_0A`, `UNPINNED_UNTIL_DECIDED`) to drop once WP-0a lands.

**How to apply:** when adding a required secret to the base Compose file, grep every test fixture's dummy env for it, and trial-merge with `git merge-tree --write-tree` against sibling WP branches before claiming done. See also [[compose-testing-traps]].
