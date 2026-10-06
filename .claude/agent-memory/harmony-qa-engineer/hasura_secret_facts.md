---
name: hasura-secret-facts
description: Measured Hasura behaviour that QA relies on when judging Hasura lockdown claims (empty admin secret, v2.11 vs v2.45, how refusals look)
metadata:
  type: project
---

Measured by QA on 2026-10-04 (WP-0a review):

- An empty `HASURA_GRAPHQL_ADMIN_SECRET=` is NOT "no secret" on v2.11.3 or v2.45.8. The secret becomes the empty string. Requests without the header are refused, but a request with an empty `X-Hasura-Admin-Secret:` header gets admin. Only `${VAR:?}` (which rejects empty and unset) is a safe Compose guard. Unsetting the variable entirely is what turns auth off.
- Refusals on `/v1/graphql` and `/v1beta1/relay` are HTTP 200 with `extensions.code: access-denied`. Assert on the code, not the status. `/v1/metadata` returns 401.
- With a role that lacks a table, Hasura says `field '<x>' not found in type: 'query_root'` or `'mutation_root'`. A role with no mutations at all says `no mutations exist`.
- Multi-operation documents: Hasura validates only the operation named by `operationName`. A prefix check on the query text in the proxy does not constrain the other operations.
- Branch metadata with `user` and `anonymous` roles loads and validates on both v2.11.3 and v2.45.8.

**Why:** the WP-0a builder documented the empty-secret case wrongly. Future Compose edits (for example `${VAR:-}`) would open admin to anyone sending an empty header.
**How to apply:** when reviewing any Hasura or secret-handling change until WP-5e retires Hasura. Related: [[legacy-stack-browser-verify]].
