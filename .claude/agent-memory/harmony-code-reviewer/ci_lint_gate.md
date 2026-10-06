---
name: ci-lint-gate
description: The PR lint gate new Python must pass (black 22.6.0 at 88 cols, pylint errors, later ruff 88) and how to reproduce it; authors' "ruff clean" claims often use ad-hoc flags
metadata:
  type: project
---

Until WP-2f lands, `.github/workflows/integration.yml` "Python - Lint" runs `black --skip-string-normalization -t py39 --check` (black 22.6.0, 88 columns) and pylint 2.17.4 on every changed `.py` file in a PR. Any pylint *error* fails the job, including E0401 for a test dependency that is not in `requirements*.txt`, such as `hypothesis`. WP-2f's planned ruff config keeps 88 columns with `quote-style = "preserve"`.

**Why:** WP-2d (2026-10-04) claimed "ruff format --check clean", but that only held with undocumented `--line-length 100`. Its 5 files failed black, and pylint E0401 fired on `hypothesis`. The lead had already treated this exact lint failure as blocking for `scripts/agents/*.py` (WP-0f Requests).

**How to apply:** for any WP that adds Python, run these from a scratch worktree:
- `uvx --python 3.9 --from black==22.6.0 --with 'click<8.1' black --skip-string-normalization -t py39 --check <files>`
- `uv run --no-project --python 3.9 --with-requirements <reqs> --with pylint==2.17.4 pylint --disable=all --enable=E <files>`

Do not trust a ruff claim unless the WP names the config it used. See [[cross-suite-collection]].
