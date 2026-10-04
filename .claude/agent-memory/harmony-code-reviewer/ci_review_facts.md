---
name: ci-review-facts
description: Verified GitHub Actions / buildx / jq facts that builders and the code-review subagent got wrong while reviewing WP-0f, plus how to review CI branches under the worktree guard
metadata:
  type: reference
---

Facts checked against source on 2026-10-04 while reviewing WP-0f. Builders and the `code-review` subagent both got some of these wrong:
- **`docker build --cache-from "a:main,a:tag"` works.** buildx `util/buildflags/cache.go` `ParseCacheEntry` turns a value with no `=` into one registry cache entry per CSV field. This has been true since at least v0.12.0. It is not "one invalid ref".
- **Default `run:` shell on Linux is `bash -e {0}`.** `--noprofile --norc -eo pipefail` applies only when `shell: bash` is set explicitly. So a simulation that uses pipefail is stricter than CI, not the same.
- **jq 1.7 `"str" + null` returns `"str"`.** So eslint messages with `ruleId: null` do not crash the annotation filter. The subagent claimed this was a defect, and it was a false positive.
- **Registries.** Actions push to `ghcr.io/<owner>/harmony-*`, and compose defaults to `ghcr.io/zenysis`. README and Makefile `DOCKER_NAMESPACE?=zengineering` point at Docker Hub, where `zengineering/harmony-*` was last pushed 2023-11-16. Check with `curl -s https://hub.docker.com/v2/repositories/zengineering/`.

**How to review a CI branch under the worktree guard:**
- `git worktree add --detach /tmp/<name> <branch>`, then work there. Remove it afterwards.
- Run `gh api` as one plain command per call. Loops or `$1` around `gh` get refused.
- Write harness files with the Write tool, not a heredoc into an interpreter.
- actionlint: `gh release download` the tarball plus its checksums, then `sha256sum -c`. For shellcheck, wrap `uvx --from shellcheck-py shellcheck`.

Related: [[wp-0f-open-items]] (infra memory)
