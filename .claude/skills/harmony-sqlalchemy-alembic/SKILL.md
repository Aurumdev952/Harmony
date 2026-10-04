---
name: harmony-sqlalchemy-alembic
description: Upgrading Harmony from SQLAlchemy 1.3 to 2.1 and writing Alembic migrations, including data migrations such as the $ref rewrite. Use when touching models/alchemy, web/server/migrations, harmony/core/db, any Session or query code, or when writing a migration. No official vendor skill exists, so this is the reference.
---

# SQLAlchemy 2.1 and Alembic in Harmony

There is no official SQLAlchemy or Alembic skill. Ground claims in the installed version's docs, not in memory: `uv run python -c "import sqlalchemy; print(sqlalchemy.__version__)"`, then read https://docs.sqlalchemy.org/en/21/.

## Upgrade path (WP-3c, WP-3e)

1. **1.3 to 1.4** with `SQLALCHEMY_WARN_20=1` and `-W error::sqlalchemy.exc.RemovedIn20Warning` in pytest. Fix every warning across the roughly 200 importing files before moving on.
2. **Remove the custom `make_declarative_base` override** in `db/sqlalchemy.py`.
3. **Move to 2.1** together with Flask-SQLAlchemy 3.1 while Flask still runs, then to plain `harmony.core.db` in WP-4b. Replace sqlalchemy-stubs with the built-in typing.

## 2.x style

- Queries use `select(Model).where(...)` with `session.execute(stmt).scalars()`. Never use `Model.query` or `session.query` in new code.
- Models use `Mapped[...]` with `mapped_column(...)`.
- Write explicit `with session.begin():` blocks. Never commit inside helpers.
- Use eager loading only where a test shows N+1: `selectinload` for collections, `joinedload` for many-to-one.

## 2.1 changes that bite

- **The default PostgreSQL driver is now psycopg 3.** Always write the driver in the URL: `postgresql+psycopg://`.
- **Python 3.11+ is required.** greenlet is no longer installed by default; asyncio needs the `[asyncio]` extra. Harmony uses sync sessions (SPEC BE-3), so do not add it.
- **`filter_by()` searches every FROM entity** and raises `AmbiguousColumnError` when a name repeats. Use `where()` with qualified columns in joins.
- **Autoflush runs before raw `text()` statements too.** Order writes accordingly.
- **Dataclass-mapped defaults no longer populate `__dict__`.**

## Sessions outside the web app

- **Celery tasks, scripts and the pipeline** build `AppContext` and use `ctx.db.session()`. They never import the Flask app. `web/server/data/data_access.py` delegates to `harmony.core.db` after WP-4b.
- **Pass ids, not ORM objects,** across task or thread boundaries.

## Alembic

- **Alembic already owns the schema.** That is 143 revisions under `web/server/migrations/versions`. Hasura only holds metadata, so retiring it (WP-5e) touches no tables.
- **Keep one head.** Run `uv run alembic heads` in CI. Merge revisions only through `alembic merge`.
- **Review autogenerate output by hand.** It misses server defaults, enum changes and some index changes.
- **Every migration has a working `downgrade()`.** If a downgrade would lose data, raise with an explanation, and record it in the WP file.
- **Data migrations** (for example WP-5g rewriting `{"$ref": "/api2/..."}` to `{"id": ...}`):
  - Make them idempotent: running twice changes nothing the second time.
  - Batch them, at 1,000 rows per transaction.
  - Log every rewrite with the row id.
  - Run them on a copy of production data first.
  - Load `pstack:principle-make-operations-idempotent`.
- **Test from scratch.** Start from an empty database, run `alembic upgrade head`, then run the seed scripts in `web/server/migrations/seed_scripts`.

## Checks

```bash
uv run pytest -W error::DeprecationWarning tests
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
uv run mypy harmony models
```
