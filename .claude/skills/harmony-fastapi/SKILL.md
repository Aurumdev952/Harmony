---
name: harmony-fastapi
description: Harmony's rules for the Flask to FastAPI migration, layered on the official fastapi skill. Use when writing or porting any HTTP route, dependency, auth flow, page shell, background-task trigger or OpenAPI output under harmony/api or web/server, or when retiring a Flask-Potion resource or the Hasura proxy.
---

# Harmony on FastAPI

Load the official `fastapi` skill (vendored in `.claude/skills/fastapi`) and `pydantic:pydantic` first. This skill records where Harmony differs from them and how the strangler migration works.

## Overrides to the official skill

- **SQLAlchemy 2, not SQLModel.** The official skill prefers SQLModel. Harmony keeps SQLAlchemy 2 with `Mapped[]` models in `models/alchemy` (SPEC BE-3). Load `harmony-sqlalchemy-alembic`.
- **mypy, not ty.** Type checking is `uv run mypy`.
- **No contrib OpenTelemetry instrumentor.** Use FastAPI's built-in telemetry (0.142+, configured through `OTEL_*` variables). Adding the contrib FastAPI instrumentor as well doubles every span.

## Application shape

- `harmony/api/app.py` builds the app. A `lifespan` context manager creates the `AppContext` (`harmony.core.context`), the Redis client and the Druid `httpx.AsyncClient`, and closes them on shutdown. Never use `on_event`.
- **One `APIRouter` per domain** (`query`, `dashboards`, `alerts`, `catalog`, `uploads`, `data_quality`, `digest`, `admin`, `users`, `config`, `auth`), under the `/api/v3` prefix (`/auth` for login flows). Authorisation dependencies go at router level.
- **Dependencies are `Annotated` aliases** in `harmony/api/deps.py`: `CtxDep`, `SessionDep`, `PrincipalDep`, `DruidDep`. Use them everywhere. Do not write `Depends(...)` inline in signatures.
- **Errors use the `ApiError` envelope** (`harmony/api/errors.py`, contract C-10). Raise domain exceptions from services, and map them in exception handlers.
- **Response models are declared through return type annotations.** Never return ORM objects.

## `def` versus `async def`

- Handlers that touch the database through sync SQLAlchemy are plain `def`. FastAPI runs them in a thread pool. Size the database pool to at least the pool's concurrency.
- Handlers that call Druid are `async def` and use the async Druid client (BE-6).
  - CPU-bound shaping runs in `await anyio.to_thread.run_sync(...)`.
  - Never call blocking I/O inside `async def`. That stalls every request on the worker.
- **Authlib (OIDC)** on Starlette is async: `await oauth.<provider>.authorize_redirect(...)`. User info comes from `token["userinfo"]`, and `request.session` needs `SessionMiddleware`.

## The strangler migration

- nginx routes `/api/v3/`, `/auth/` and `/render/` to uvicorn, and everything else to Flask. Do not mount Flask inside FastAPI.
- **Both apps accept the same session.** The `accessKey` cookie is an HS256 JWT signed with the JWT secret (contract C-5).
  - The FastAPI `PrincipalDep` must accept, in this order: the cookie, an `Authorization: Bearer` API token (checked against the `APIToken` table for revocation), then `X-Username` / `X-Password` headers.
  - It must accept the flask-jwt-extended 3 claim layout (`identity`, `user_claims`) until the longest-lived cookie has expired.
  - The reference behaviour is `web/server/security/signal_handlers.py:287-339`.
- **One domain per WP.** For each domain:
  1. Port the routes.
  2. Switch the frontend to the generated client (contract C-4).
  3. Delete the Potion resource and the old frontend service in the same PR.
  4. Replay `tests/contract/` cases for the domain against FastAPI.
- **Wire format.**
  - Responses carry `id`, not `$uri`.
  - List endpoints use `?filter[field]=`, `?sort=-field`, and `?page[size]=` with `?page[cursor]=`, and put `total` in the body.
  - Requests still accept stored `$ref` objects through `harmony.core.refs.parse_legacy_ref` until WP-5g.
- **Potion behaviours you must reproduce explicitly:**
  - the `before_create`, `before_update` and `before_delete` authorisation signals (`web/server/security/signal_handlers.py:341-381`), which become `can(principal, action, resource)` calls in the service;
  - `X-Total-Count`, used by `web/python_client`;
  - `id_attribute` overrides, such as dashboards keyed by `resource_id` and configuration keyed by `key`.

## Long-running work

- Exports, self-serve imports (`web/server/routes/api.py:196-207`), and email and SMS run as Celery tasks. Load `harmony-celery`.
- The route returns `202` with a job id, and the client polls or streams progress.
- Uploads stream to object storage. Never read 128 MB into memory.

## OpenAPI and the client

- Every route has a stable `operation_id` (`<router>_<verb>_<noun>`) so generated hook names stay stable.
- CI regenerates `web/client/api/generated/` with `@hey-api/openapi-ts` and fails when the committed output differs. Commit the regenerated client in the same PR as the route change.

## Checks

```bash
uv run pytest tests/contract -k <domain>
uv run pytest harmony/api
uv run mypy harmony
uv run ruff check harmony
```

Also exercise one real request through nginx with a Flask-issued cookie.
