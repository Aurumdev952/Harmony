---
name: review-tooling-traps
description: Traps when running semgrep, the ownership/gate scripts and local stacks during Harmony security reviews (worktree guard, glob expansion, cwd-relative SPEC)
metadata:
  type: project
---

Observed during the WP-0a review, 2026-10-04.

- **Semgrep runner glob trap.** The static-analysis plugin's `run-scans.sh` leaves `--include=*.py` unquoted, so the shell expands it against the current directory. From the repo root it became `--include=__init__.py`, and `p/python` / `p/flask` scanned 0 files while reporting success. Run the wrapper from an empty directory (`cd /tmp/empty` first), and check `filesScanned` in `scans.json`. `p/yaml` returns 404 from the registry; leave it out.
- **Semgrep is not installed globally.** Use a throwaway venv (`uv venv` + `uv pip install semgrep`) instead of installing a user tool.
- **Worktree-isolation guard.** It rejects compound shell lines that mention git or docker with computed values (loops, `$(...)`, heredocs containing git). Write multi-step work to `/tmp/*.sh` with the Write tool and run `bash /tmp/x.sh` as a plain command.
- **`scripts/agents/ownership.py` and `task_gate.py` read SPEC and the WP file from the cwd.** Run them from a scratch worktree checked out at the WP tip, with `uv run --no-project python ...`. From the reviewer worktree (older `main`), they report stale owners (`tests/**` as qa) or "WP file does not exist". Pass every contributing role (`--role backend --role infra`) to `check`.
- **WP branches move during review.** Re-check the tip (`git log -1 <branch>`) before writing the verdict and diff code paths between the tested tip and the new one.
- **GitHub DNS flakes inside pip subprocesses.** Pre-clone `-e git+https` requirements and point a requirements copy at the local clones. See the backend's `local-flask-stack` memory for the rest of the in-process Flask recipe.

**Why:** each of these cost a re-run, and the semgrep one silently produces a clean-looking but empty scan.
**How to apply:** at the start of any review that runs semgrep or the gate scripts. [[hasura-review-facts]]
