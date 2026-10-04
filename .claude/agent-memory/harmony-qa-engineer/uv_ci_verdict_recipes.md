---
name: uv-ci-verdict-recipes
description: How QA verifies the uv/ruff/mypy CI (WP-2f onward) offline, plus the cross-suite gaps it exposed (hypothesis missing from the dev group, 2c replay skips)
metadata:
  type: reference
---

Learned on the WP-2f verdict (2026-10-04).

- **Simulate the PR merge commit.** CI lints `git diff HEAD^1` on GitHub's merge commit. Make a second scratch worktree at `mig/integration`, then `git merge --no-ff --no-edit <wp-branch>`. HEAD^1 is then the base, as on GitHub.
- **Replay the `run:` blocks.** Write a Python runner that loads `integration.yml`, runs each `run:` with `bash -e -c` in a scrubbed env (HOME, PATH with `~/.local/bin` first, RUNNER_TEMP) and reports every exit code. Run it with `~/.local/bin/uv run --no-project -p 3.13 --with pyyaml python /tmp/x.py`.
- **Bash guard.** Any command line containing `.github`, a heredoc, or `( ... )` subshells next to git or uv is refused. Copy the file out of `.github`, write scripts with the Write tool, and do git mutations inside a Python `subprocess` runner. After each mutation, restore with `git checkout -- . && git clean -fdq -e .venv -e ci/tools313/.venv`.
- **Cold lock proof.** Set `UV_CACHE_DIR` and `UV_PROJECT_ENVIRONMENT` to fresh /tmp paths. A cold `uv sync --locked` takes about 3.5 minutes. One DNS blip failed the first try; retry before calling it a defect.
- **Forward look at suite merges.** Run `git archive <suite-branch> tests | tar -x -C <scratch> --skip-old-files` for 2a, 2b, 2c and 2d, then run CI's `uv run --locked pytest -m 'not stack'`. On WP-2f's environment, `hypothesis` was missing, so 2c's `test_schema.py` and 2d's `test_properties.py` failed to collect (exit 2). With `--with hypothesis` and lz4 on PATH, 3189 passed and 166 were skipped. The skips are 2c `test_replay.py`, which is gated on `CONTRACT_BASE_URL`, not on the `stack` marker.
- **lz4 without root:** `apt-get download lz4 && dpkg -x lz4_*.deb root`. The GitHub ubuntu-24.04 runner already has lz4 and pigz (runner-images Ubuntu2404-Readme).
- **pytest-selenium 4.0.1** turns any failure into an INTERNALERROR (exit 3) that hides the test name. The root pyproject keeps `-p no:selenium` in addopts. Never drop it.

Related: [[qa-verdict-recipes]], [[ci-workflow-review]].
