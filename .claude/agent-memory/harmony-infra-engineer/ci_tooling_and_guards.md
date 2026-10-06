---
name: ci-tooling-and-guards
description: How to lint GitHub Actions locally in a Harmony worktree, resolve action SHAs, and get past the worktree-isolation Bash guard
metadata:
  type: reference
---

- **actionlint is not installed.** Download the release tarball and `actionlint_<v>_checksums.txt` into `/tmp`, check them with `sha256sum -c`, and run the binary with `-shellcheck <path> -oneline`. For shellcheck, wrap `uvx --from shellcheck-py shellcheck "$@"` in a tiny script and pass that script's path.
- **Resolving an action tag to its commit SHA:** `gh api repos/<owner>/<action>/commits/<tag> --jq .sha`. Run it from the worktree as one plain command per action.
- **The worktree-isolation guard** refuses Bash commands that mention git or gh inside loops, heredocs fed to interpreters, `curl ... github.com`, or `bash -c`. Write files with the Write or Edit tools. Put test harnesses in `/tmp/*.py` and run them with `uv run --no-project --with pyyaml==6.0.2 python <file>`. `python3` is blocked by a hook, so use `uv run python`.
- **Simulating `run:` blocks:** load the YAML and execute each `run:` against stub binaries on `PATH`, giving each step only its own `env:`. Use `bash -e -c`. When `shell:` is unset, the Actions default is `bash -e {0}`, with no pipefail. `bash --noprofile --norc -eo pipefail {0}` applies only when `shell: bash` is explicit. This caught array and quoting behaviour without a PR run.
- **As of 2026-10-04 the current action majors** were checkout v7, setup-python v7, setup-node v7, cache v6 and docker/login-action v4. The phase files say v4/v5, which is stale. Re-check before pinning: see WP-0f "Decisions".
- **actionlint finds no project outside a git repo.** To check that it and shellcheck are really running, pass the path to a deliberately bad workflow file directly; running it from a `/tmp` dir exits 3.
- **zizmor `--persona=auditor`** also flags `undocumented-permissions`, which wants the reason on the same line (`packages: write # push the image`); a comment on the line above does not count. It also flags `anonymous-definition` for jobs without `name:`.
- **`docker build --check` on an ARG-only `FROM ${IMAGE}`** warns `InvalidDefaultArgInFrom` even when `--build-arg` is passed. Add `# check=skip=InvalidDefaultArgInFrom` rather than a default image name that could be pulled from Docker Hub.
- **Workflow tests in `tests/infra` use pyyaml** (in `ci/tools313`'s dev group since WP-1h infra-2). PyYAML reads the bare key `on` as `True`.
- **No Dependabot config exists** for `github-actions` yet, so SHA pins go stale silently. WP-2f should add one. See [[wp-0f-open-items]].
