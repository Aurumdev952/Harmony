---
name: potion-route-test-harness
description: How to test /api2 Potion routes through the real Flask app without Docker images or Druid (throwaway Postgres, create_all, header login), and the traps hit doing it
metadata:
  type: reference
---

`tests/web/privilege_escalation/conftest.py` (WP-0h, 2026-10-04) is a reusable pattern for exercising Potion routes with constructed users:

- `create_app_base(FlaskConfiguration())` with `SQLALCHEMY_DATABASE_URI` pointed at a throwaway `postgres:15.2-alpine` (`docker run -p 127.0.0.1::5432`), `db.create_all()`, then seed by hand: `UserStatus`, `ResourceType`, `QueryPolicyType`, the roles you need, and `_populate_configuration_table(session)`. Without the configuration rows every request 500s in `is_public_dashboard_user`.
- Needs `initialize_zenysis_module`, `app.cache` (flask_caching `null`), a stub `app.user_authentication_router.unauthorized`, `initialize_user_manager`, `JWTManager`, `_register_principals`, then `_register_potion_routes` with `web.server.api.api_models.list_query_resource_types` patched to `[]` (query resources read Druid).
- Header login (`X-Username`/`X-Password`) needs `--with 'bcrypt<4.1'`.
- Session-scoped app only: Potion resource classes are module singletons and signal handlers attach per class.
- Every request's app-context teardown calls `session.remove()`, detaching ORM objects the test loaded earlier. Hold ids in tests and re-query with `expire_all()`.
- `ZenysisLogger` does not propagate; attach `caplog.handler` to it to assert audit lines.
- Seeded role relationships `dashboard_resource_role` are `viewonly`; set `dashboard_resource_role_id`.

The WP-2b live-stack layer can run against any tree: `git archive` the branch plus `tests/authz` (WP-2b) and `tests/contract/stack` (WP-2c) into /tmp, then `AUTHZ_PROJECT=<unique> AUTHZ_WEB_PORT=<free> tests/authz/stack.sh up` (source is bind-mounted, image `harmony-wp2c-web-server:local`). About 3 minutes per run.

Authz traps found in WP-0h:
- `GroupResourceManager` and `RoleResourceManager` scope item routes too, so non-members and non-holders get 404 before any handler runs. Probe before you "fix" a path that reviewers reason about from the handler alone.
- `User.is_superuser()` reads the account; `SuperUserPermission().can()` reads the (possibly JWT-narrowed) identity. Use the identity when deciding what a caller may grant.
- Never trust `QueryNeed` containment to mean "more data": policies are ORed per dimension and ANDed across dimensions in `_construct_authorization_filter`.

Worktree guard: heredocs and `git -C <other worktree>` are refused; use Write/Edit for file content and `git show`/`git archive` from your own worktree.

Related: [[flask-local-test-env]], [[local-flask-stack]]
