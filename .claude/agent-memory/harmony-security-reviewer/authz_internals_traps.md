---
name: authz-internals-traps
description: Non-obvious facts about Harmony's grant, query-policy and session code that decide whether an authz finding is real
metadata:
  type: project
---

Facts verified while reviewing WP-0h (2026-10-04); re-check the code before relying on them.

- DB query policies are single-dimension (one value or all), unique per (dimension, value). Multi-dimension (complex) QueryNeeds only come from JWT `query_needs`, and no issuer sends them (browser and API tokens use `'*'`, render tokens `'*'`).
- The policy filter is monotone in the DB policy set, so removing a policy never widens access. `EmptyFilter.__or__` returns the other operand, which makes it non-monotone only with complex needs.
- Per-dimension additive policies compose: conferring a held single-dimension policy can complete another user's cross product (they see data the conferrer cannot). This is inherent in grant-based rules like decision 0004's.
- `find_one_by_fields` runs in a committing `Transaction`, so a later exception in the same request does not roll back earlier pending changes. The legacy `/roles` adds return 500 after the unlink has been committed.
- Two notions of superuser coexist: `SuperUserPermission().can()` (identity) and `current_user.is_superuser()` (account, used by the Potion managers and `create_group`). They differ only for narrowed admin tokens.
- `UserResourceManager` hides only direct admins. Admin-through-group users can be edited (username included) and reset by manager+user_admin, which is an account-takeover path (WP-2b H5).

**How to apply:** use these to triage candidate findings quickly, but confirm with a live probe against base and head.
