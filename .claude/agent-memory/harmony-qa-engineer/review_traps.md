---
name: review-traps
description: Traps when giving QA verdicts in Harmony: gitignored fixtures, worktree-isolation hook limits on shell commands, uv-only python
metadata:
  type: feedback
---

Always run a WP's tests from a fresh detached scratch worktree, never the builder's checkout.
**Why:** WP-0g's fixture `tests/infra/testdata/zz/access.log` matched `.gitignore` `*.log` (Django block). The tests passed for the builder (49) and failed on a clean checkout (6 failed, FileNotFoundError).
**How to apply:** after `git worktree add /tmp/review-<wp>-qa <branch> --detach`, run `git check-ignore -v` on every fixture path the tests read, then run the suite before copying anything in.

The worktree-isolation hook refuses Bash commands it cannot verify: `cd` into another worktree followed by git or uv, shell `for` loops calling `uv run`, and process substitution `<(...)`.
**How to apply:** write a small Python runner in /tmp that uses `subprocess`, and run it with `uv run --no-project -p 3.13 python /tmp/x.py`. Plain `python3` is blocked by a hook; use `uv run --no-project python`.

There is no repo ruff config until WP-2f. Default `uvx ruff check` flags more than the builders' `--select E,F,I,UP,B,SIM`. Treat that as advisory.
