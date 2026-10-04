---
name: actions-review-tooling
description: Commands that work for reviewing GitHub Actions WPs in Harmony (zizmor, actionlint, SHA/advisory checks) and the environment traps around them
metadata:
  type: reference
---

- **zizmor is the main Actions auditor.** `GH_TOKEN=$(gh auth token) uvx zizmor --format=plain .github/workflows/`. The token turns on the online audits (impostor-commit, known-vulnerable-actions, ref-version-mismatch, stale-action-refs). Check with `-v` that they were scheduled. `--persona=auditor` adds low and informational items. Run it on `main`'s workflows too (extract them with `git show main:<path>`) so the verdict can quote before and after.
- **actionlint:** use the release tarball plus `actionlint_<v>_checksums.txt` (`sha256sum -c`). For shellcheck, run `uvx --from shellcheck-py python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'shellcheck'))"` and pass the printed path to `-shellcheck`.
- **Pin to tag:** `git ls-remote --tags https://github.com/<o>/<r>.git refs/tags/<t> 'refs/tags/<t>^{}'`. To prove a SHA is not a fork-only impostor commit, `gh api repos/<o>/<r>/compare/<sha>...<default-branch>` must return `ahead`, and `behind_by` must be 0.
- **Advisory DB:** `gh api -X GET /advisories -f ecosystem=actions -f affects=<o>/<r>`. Run a control query on `tj-actions/changed-files`, which returns 2, so that an empty result really means none.
- **Traps:**
  - The worktree guard refuses `git`/`gh` inside loops or with computed args, so use one plain command per call.
  - `uv pip install` is intercepted by a plugin shim, so use `uvx`.
  - `scripts/agents/ownership.py` must run as `uv run python ...`.
  - In zsh, an unmatched glob aborts the whole line.
- The supply-chain-risk-auditor collector does not cover the Actions ecosystem. For Actions, measure pins as above and say that the collector does not apply.

Related: [[actions-trust-model]]
