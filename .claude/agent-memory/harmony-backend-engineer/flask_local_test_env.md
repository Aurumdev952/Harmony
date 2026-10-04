---
name: flask-local-test-env
description: How to import and build the Flask app locally without Docker (Python 3.8 uv env, required env placeholders, mocks for _register_routes), and worktree-guard traps
metadata:
  type: reference
---

There is no pyproject yet. Build a throwaway env from the pinned requirements (recipe in WP-0c.md "How to run the tests"):
rewrite `-e git+...#egg=X` lines to `X @ git+...`, then
`PYTHONPATH=<worktree> uv run --no-project -p 3.8 --with-requirements /tmp/reqs.txt --with 'pytest<8' python -m pytest tests/web -q -p no:cacheprovider -W ignore`.

- `create_app(skip_db_check=True)` also needs `SQLALCHEMY_DATABASE_URI` (any placeholder URL); otherwise `util/flask.py` reads `POSTGRES_USER`. `DEFAULT_SECRET_KEY`, `DRUID_HOST`, `ZEN_ENV=harmony_demo` come from `tests/web/conftest.py`.
- `_register_routes` needs `app.template_renderer`, `app.druid_context` and `app.cache` mocked, and `_initialize_query_data(app)` run inside `app.app_context()` first. With that, the route map runs offline and matches the Docker-image map exactly (316 rules on main as of 2026-10-04).
- Worktree isolation guard refuses Bash that uses shell variables in the command path, `cd ... && export ...; uv ...` chains, or Python heredocs whose text mentions git. Use literal absolute paths, one command per call, and the Edit tool for doc edits.
- `web/server/app.py` is not black-clean on main; do not reformat it in an unrelated WP.

Related: [[template-render-diff]]
