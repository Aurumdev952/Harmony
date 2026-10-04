---
name: ci-workflow-review
description: How QA verifies GitHub Actions workflow changes offline in Harmony (actionlint, SHA checks, run-block simulation with hostile filenames) and the worktree Bash-guard traps
metadata:
  type: reference
---

- **Bash guard.** Commands that combine `git`/`gh` with loops, pipes into `while`, or heredocs are refused. Run `gh api repos/<o>/<r>/commits/<tag> --jq .sha` one call per line from your own worktree. Write harness files with the Write tool into `/tmp`, not with heredocs.
- **actionlint.** Download the release tarball and checksums into `/tmp/qa0f`, then run `sha256sum -c`. For shellcheck, use a two-line wrapper: `exec uvx --from shellcheck-py==0.11.0.1 shellcheck "$@"`. Get a `main` baseline with `git archive main .github | tar -x -C <dir>`.
- **Run-block simulation.** Load the workflow YAML and run each `run:` with both `bash -e -c` (the Actions default when `shell:` is unset) and `bash --noprofile --norc -eo pipefail -c`. Use stub `gh`, `black`, `pylint`, eslint and stylelint that record argv NUL-separated. Use hostile filenames: `$(touch PWNED).py`, names with spaces, `g*.py` next to `gz.py`, a leading space, and a backslash. To compare against `main`, first render `${{ github.head_ref }}` to a literal with `sed`, or bash dies on bad substitution.
- **Makefile.** Always pass `ENV_FILE=/dev/null`. The Makefile `-include`s `.env`, and agents must never read it.
- **Image workflows** run only on `push` to `main` and `workflow_dispatch`, so only `integration.yml` can go green on a PR. Related: [[wp-0f-open-items]] in infra memory.
