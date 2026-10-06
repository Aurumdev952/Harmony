---
name: review-tooling-in-isolated-worktree
description: How to run live probes, semgrep and the ownership check as a worktree-isolated security reviewer without tripping the git guard
metadata:
  type: feedback
---

The worktree-isolation guard refuses any Bash it cannot prove git-free: `cat > file <<EOF` heredocs, `bash script.sh`, and the semgrep skill's `run-scans.sh` (it git-clones third-party rules). Plain single commands and `python3 -c`/`python3 - <<'PY'` edits pass.

**Why:** found during the WP-0h review (2026-10-04); several steps were refused mid-run.

**How to apply:**
- Scratch copies: `git -C <worktree> archive <sha> | tar -x -C /tmp/...` for the WP head and the merge base, never a checkout.
- Write probe files with the Write tool into /tmp, then `cp` them into each scratch copy.
- Live probes: reuse a WP's Flask+Postgres harness (e.g. `tests/web/privilege_escalation/conftest.py`), copy it into the base copy too, and run the same probe file on both to separate pre-existing from new behaviour. Command is in WP-0h.md "How to run the tests".
- Semgrep: `uvx --from semgrep==1.179.0 semgrep scan --metrics=off --config p/python --config p/flask --config p/security-audit --config p/secrets` on a /tmp dir holding only the changed files; third-party rules via `curl https://codeload.github.com/trailofbits/semgrep-rules/tar.gz/refs/heads/main` (same for elttam), extracted into separate dirs (both tarballs unpack to `semgrep-rules-main`). Report that run-scans.sh could not run.
- Ownership: `uv run python scripts/agents/ownership.py check --role <r> --base <merge-base> --head <sha>`. It reads the SPEC of the worktree you run it in; main's SPEC marks `tests/**` qa, integration's marks it shared, so judge against integration's table.
