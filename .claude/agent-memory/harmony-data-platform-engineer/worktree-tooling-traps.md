---
name: worktree-tooling-traps
description: Commands the isolated-worktree Bash guard rejects and what works instead; pytest basename clash with tests/infra
metadata:
  type: feedback
---

- In an isolated worktree, the Bash guard rejects heredocs, `for` loops that run docker or curl with variables, `docker --format '{{...}}'`, `sed` programs built from shell variables, and anything that sets HOME. Write scripts and files with the Write tool, and run plain one-line commands. Use `uv run --no-project python <script>`, because bare `python3` is blocked by a hook.
- `tests/druid_setup/test_compose.py` collided with `tests/infra/test_compose.py`: there is no `__init__.py`, so pytest saw two modules with the same basename. Prefix test files with the area (`test_druid_*.py`).
- `scripts/agents/check_team.py` needs `uv run --no-project --with pyyaml`.

**Why:** These rejections and clashes wasted several turns in WP-0b R4.
**How to apply:** Follow these from the first command in any worktree session.
