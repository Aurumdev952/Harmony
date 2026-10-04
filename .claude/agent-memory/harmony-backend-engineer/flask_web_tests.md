---
name: flask-web-tests
description: Run tests/web on py3.8 without a running app; traps in Harmony auth, query-policy filters (pydruid & mutates), druid_context caches
metadata:
  type: reference
---

**Running tests/web** (Python 3.8, Flask 1.0.1, flask-jwt-extended 3.25.1, flask-login 0.4.1): build `/tmp/reqs.txt` with the sed/grep recipe in `docs/modernisation/work/WP-0c.md` ("How to run the tests"), then `PYTHONPATH=$PWD uv run --no-project -p 3.8 --with-requirements /tmp/reqs.txt --with 'pytest<8' python -m pytest tests/web`.
- Call a route handler directly via `Router.method.__wrapped__(router, ...)` inside `app.test_request_context`; `authentication_required` uses `functools.wraps`.
- For full request tests use a bare Flask app + `JWTManager` + a `LoginManager` whose `request_loader` mirrors `signal_handlers.py` (JWT identity signs the user in on every request). See `tests/web/test_timeout_route.py`.
- Tests must run on 3.8: `from __future__ import annotations` makes `set[...]`/`X | None` fine in annotations, but never subscript builtins at runtime (module-level aliases).
- ruff config in the repo enforces UP/DTZ rules on tests; use `datetime.fromisoformat(...)` for naive datetimes.

**Worktree guard traps**: Bash refuses `git` inside compound commands, `sed`/args computed from shell variables, and `PYTHONPATH=... python` combined with other steps. Run `git show X:path > /tmp/f` alone, and test runs alone.

**Code traps** (verify before relying on them):
- Flask-Login `logout_user()` does not end a JWT session: the `accessKey` cookie signs the user back in on the next request. Use `unset_jwt_cookies`.
- `druid_context.data_time_boundary` builds a new `DataTimeBoundary` per access, so its cache never survives a request; `row_count_lookup` is `lru_cache`d per datasource and its cache is process-wide.
- `EmptyFilter` builds as `None`; `Filter(type='and', fields=[EmptyFilter(), f])` sends `null` to Druid. Never fix that with pydruid's `&`: `Filter.__and__`/`__or__` append into an existing `and`/`or` IN PLACE (flattens the request = golden diff, mutates shared filters). Use `query_policy.and_policy_filter`.
- The caller's policy is `query_policy.caller_policy_filter()` (None for superuser, anonymous public access, or an empty policy). Resolve it once per request and reuse it; do not re-derive the superuser/public rule.
- A `GroupByQueryBuilder.query_filter` can be `EmptyFilter`/`None` for a known field (missing constituents, unfiltered aggregations such as theta sketch without `filter_field`): a raw lookup with it counts every row.
