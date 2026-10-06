---
name: ruff-format-py38-trap
description: ruff format (target py39) rewrites multi-item `with` into parenthesized groups that the web image's Python 3.8 rejects; check touched web/server files parse under 3.8
metadata:
  type: project
---

`ruff format` on a touched `web/server` file rewrites `with A(...), B(...):` into the parenthesized `with (\n A,\n B,\n):` form. pyproject targets 3.9 (`requires-python`), but the web image (`docker/web/Dockerfile_web-server`) runs Python 3.8.20, which raises SyntaxError at import, so gunicorn fails to boot. `uv run pytest` (3.9) and mypy stay green, so nothing local catches it.

**Why:** found in WP-0k (2026-10-05). The CI lint gate formats every changed file, so any backend WP that touches a file with a multi-item `with` hits it.

**How to apply:** after `ruff format`, grep the diff for `with ($`. Rewrite those as nested `with` statements (ruff keeps them). Then parse `web/server` with the image's Python: `docker run --rm -v <tree>:/z:ro harmony-contract-web-server:<hash> python -c "import ast,pathlib; [ast.parse(p.read_text(), str(p)) for p in pathlib.Path('/z/web/server').rglob('*.py')]"`. This holds until WP-3b moves the image to 3.13.
