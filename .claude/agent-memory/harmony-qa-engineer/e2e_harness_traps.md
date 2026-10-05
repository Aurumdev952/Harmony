---
name: e2e-harness-traps
description: WP-2e Playwright harness traps - visual in pinned image, a11y/visual before e2e, settle before axe, container DNS after reboot
metadata:
  type: project
---

Learned 2026-10-05 finishing WP-2e units 4-5 (`e2e/`):

- Pixels are only reproducible in the pinned Playwright image, so `e2e/run.sh` runs the `visual` project in that image. The image reaches the stack through `--network container:<forward>` at `127.0.0.1:5000`. Its tag must match `@playwright/test` in `e2e/package.json`. `tests/visual.spec.ts` refuses to run without `E2E_VISUAL_IMAGE`.
- The a11y node counts and the screenshots describe the stack as seeded. The e2e project adds dashboards, users and sources: the overview row count and data-upload's contrast nodes change. That is why run.sh runs visual, then a11y, then e2e, as separate invocations.
- Run axe or a screenshot only after `openSettled` (`support/pages.ts`), which waits until `.zen-loading-spinner` and `.fallback-pill` are both gone. A `ready` text appears before the Suspense fallback resolves. One baseline was recorded on the skeleton once, and so was a snapshot.
- Plotly's first draw at 1440 px gave different tick spacing on two runs of the same query. Capture charts only after a viewport resize.
- A project-level `expect` in playwright.config replaces the top-level `expect` object (timeout included). Put `toHaveScreenshot` options at the top level.
- After a host reboot, rootless Docker containers could not resolve names through the router (192.168.1.254), while `--network host` and `--dns 1.1.1.1` both worked. `stack.sh` always runs `docker build`, so the pip layer failed on github.com. The local workaround, never committed, was a `docker` wrapper first on PATH that adds `--network host` to `build`.

**Why:** each of these cost a red run to find.
**How to apply:** reuse `openSettled` for whole-page checks. Keep any new state-sensitive suite ahead of the e2e project in run.sh. See [[reference-contract-stack]].
