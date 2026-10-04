---
name: ci-review-checks
description: Non-obvious defects to check in Harmony CI/toolchain WPs (setup-uv cache key sharing, changed-file base semantics, cross-WP requests addressed to the WP)
metadata:
  type: project
---

Three defect classes found in the WP-2f review (2026-10-04). Check for them again in later CI work: WP-2g, WP-3b, and any job added for stack, e2e or pipeline suites.

1. **setup-uv cache keys are not job-specific.**
   - The key comes from arch, OS, the detected Python (`uv python find` in working-directory), and a hash of the default glob over every `**/pyproject.toml`, `**/uv.lock` and `**/*requirements*.txt`.
   - Two jobs in the same directory therefore share one key. The fast job saves first. The slow job's save is lost, and later exact hits never re-save.
   - Each extra uv job needs a `cache-suffix`.
2. **"Changed files" scripts must diff from the merge-base** (`git diff --merge-base <base>`), not from the base tip. Otherwise local `make lint-python` or `format-python` drags in, and rewrites, files changed on main since the branch point. In CI, `HEAD^1` of the PR merge commit is already the merge-base.
3. **QA WPs file requests addressed to infra WPs** (WP-2c and WP-2d both asked WP-2f for deps and CI jobs). Grep every in-flight `docs/modernisation/work/WP-*.md` on the other branches for `infra (WP-<id>)` and confirm the WP under review answers them (SPEC 7.3).

**Why:** none of these show up in the builder's own evidence, which ran when integration equalled the merge-base and before any GitHub run.

**How to apply:** for any CI or toolchain WP, read the third-party action's source at the pinned SHA for its cache and token behaviour. Re-run its scripts after integration has moved.
