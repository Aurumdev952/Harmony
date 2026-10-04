---
name: reference-shell-hooks
description: Which Bash shapes the worktree-isolation and python hooks refuse for QA agents, and the forms that work
metadata:
  type: reference
---

Hooks seen while reviewing WP-2c (2026-10-04) as a worktree-isolated QA agent:

- `python3 script.py` is refused ("use `uv run python`"). Use `uv run --no-project python ...`
  (add `--with requests` etc. as needed).
- Commands mixing `cd /tmp/... && git ...`, docker `--format '{{...}}'`, `eval "$(...)"`, heredocs
  feeding python, or `for` loops over `git` output are refused as "too complex to verify".
  Split into one plain command per call; write helper scripts with the Write tool and run them.
- `git worktree add --detach /tmp/<name> <branch>` from the own worktree works; plain `git status` inside
  that /tmp worktree works; `git grep <branch> -- <paths>` from the own worktree works for cross-branch checks.
- For env-dependent runs (contract stack), a small wrapper script that exports the env vars and runs
  `"$@"` avoids `eval`. See [[reference-contract-stack]].
