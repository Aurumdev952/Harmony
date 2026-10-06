---
name: lint-typecheck-commands
description: How to run mypy and ruff on Harmony files before WP-2f lands tooling (mypy absent from venv, sqlmypy plugin, no ruff config)
metadata:
  type: reference
---

- `uv run mypy` fails: mypy is not a project dependency. `uvx mypy` fails too, because `mypy.ini` loads the `sqlmypy` plugin. What works: `uvx --with sqlalchemy-stubs mypy --ignore-missing-imports --follow-imports=silent <files>`.
- There is no ruff config yet, so `uvx ruff format --check` wants double quotes everywhere. The codebase uses single quotes, so do not run `ruff format`. Use `uvx ruff check <files>` only, and compare against the base (`git show <base>:<file> | uvx ruff check --stdin-filename <file> -`) so you can separate pre-existing findings from new ones.
- `tests/authz` does not exist yet (as of 2026-10-04). `tests/golden` is the only suite in `testpaths`.
- The bypass-mode worktree guard rejects compound bash commands that contain heredocs. Write files with the Write tool.
