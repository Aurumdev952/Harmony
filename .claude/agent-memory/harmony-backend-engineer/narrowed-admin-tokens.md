---
name: narrowed-admin-tokens
description: Superuser must come from the identity, not the account; narrowed JWTs (the render token) on admin accounts and how Potion managers decide reach — key for any authz/identity port (PrincipalDep, C-5)
metadata:
  type: project
---

`current_user.is_superuser()` asks the account. `SuperUserPermission().can()` (= `current_user_is_superuser()`) asks the identity. They differ for JWTs whose `needs` claim is not `['*']`: `_compute_token_item_needs` drops `RoleNeed('admin')`. The render token (`page_renderer.py`, the admin render bot, narrowed to view one dashboard) is such a token in production, so "no narrowed tokens are issued" is false.

**Why:** in WP-0h (2026-10-04) a narrowed admin token could still confer admin. The role and group Potion managers (`web/server/potion/managers.py`) decided item reach from the account, and item routes such as `PATCH /api2/role/<id>/users` and the group `/users` routes confer whatever they reach. The fix: identity for superuser everywhere a grant is decided, held grants from the account minus admin, pinned by `test_a_narrowed_admin_token_cannot_grant_through_any_path`. `UserResourceManager` and `QueryPolicyResourceManager` still use the account, left for WP-0i, because the render bot reads users.

**How to apply:** when porting auth (PrincipalDep, C-5) or any authz check to FastAPI, derive "is superuser" from the token's effective needs, never from the user row, and add a full-session-versus-narrowed-token test for each grant path.
