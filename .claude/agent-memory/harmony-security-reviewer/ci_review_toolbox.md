---
name: ci-review-toolbox
description: Commands and traps for reviewing Harmony CI/workflow/supply-chain WPs (actionlint, zizmor, setup-uv, ownership, sandbox)
metadata:
  type: reference
---

- **Pinned scanners.** actionlint 1.7.12 release tarball, checked with `sha256sum -c` against
  `actionlint_1.7.12_checksums.txt`. zizmor has no checksum file; verify the release tarball
  with `gh attestation verify <tgz> --repo zizmorcore/zizmor` (exit 0 = Sigstore OK). shellcheck:
  `uv tool run --from shellcheck-py==0.11.0.1 shellcheck`; pass its path to `actionlint -shellcheck`.
  Run zizmor twice: `--offline` (default persona) and online `--persona=auditor` with
  `GH_TOKEN=$(gh auth token)`, and report both counts for base and head.
- **Baselines (2026-10-04, mig/integration 9f1a20e):** actionlint 0; zizmor default 0 (15
  suppressed); zizmor auditor 15 (6 info, 9 low, 0 medium). A new dependabot.yml without
  `cooldown` adds one `dependabot-cooldown` medium per update entry.
- **setup-uv v10.2.0** (`c18668ad...`): checksum comes from the embedded `KNOWN_CHECKSUMS`
  (takes precedence over the network manifest); GITHUB_TOKEN is only sent when the download
  origin is github.com, not to the Astral mirror. Cache key has no per-job component, so two jobs
  with `enable-cache` and no `cache-suffix` collide.
- **Ownership check:** run `scripts/agents/ownership.py` from a `mig/integration` worktree. The
  copy in this agent worktree can be older and mislabel `tests/**` as qa.
- **Sandbox traps:** `python3` is shimmed to an error; use `/usr/bin/python3` or `uv run`. The
  worktree-isolation hook refuses compound Bash that `cd`s to /tmp with loops or `$(...)` in gh
  args; use plain one-tool commands and the Write tool for scratch files.
- **Filename option injection:** `ruff check "${files[@]}"` without `--` accepts a file named
  `--config=lint.select=["E9"]#.py` as an option. Not a privilege boundary on `pull_request`
  (the PR controls the workflow), so report as low hardening only.
