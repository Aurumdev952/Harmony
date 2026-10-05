---
name: renderer-chromium-sandbox
description: Hardening traps for the Playwright/Chromium renderer and render-egress containers (WP-1h) - SYS_CHROOT, init for Python PID 1, same-host cookie leak to map origins, in-image tests, network pools
metadata:
  type: project
---

- **cap_drop ALL plus Playwright's seccomp profile kills Chromium.** Docker evaluates the profile's `includes.caps` rules against the container's capabilities. `chroot` is allowed only with CAP_SYS_CHROOT, so the zygote dies with `Check failed: sys_chroot("/proc/self/fdinfo/") == 0`. Fix: `cap_add: [SYS_CHROOT]`. A non-root pwuser still has CapEff 0, and its bounding set holds only SYS_CHROOT. Keep the profile byte-identical to upstream so its sha256 can be audited.
  **Why:** the WP-1h proposal and its unit-5 check only probed /healthz under cap_drop ALL and never launched a browser, so the breakage went unnoticed.
  **How to apply:** prove any browser-container hardening with a real launch (`chromium_sandbox=True`, then `page.pdf()`) or with the in-image suite under exactly the Compose flags.
- **Use `init: true` for any service whose PID 1 spawns browsers.** Each closed Chromium leaves about 2 zombies on a Python PID 1, and they count against pids_limit.
- **Use `init: true` for any Python PID 1, not just browser hosts.** Python as PID 1 ignores SIGTERM. Measured for `render-egress` (2026-10-05): `docker stop` took 16 s without an init and 0.3 s with one.
- **Chromium sends the web origin's cookies (`accessKey`, the render token) to a map origin on the same host but another port.** Cookies are scoped to a host, not a port. A logging stand-in proxy showed it. `render-egress` dropping `Cookie` is load-bearing, not defence in depth. When proving a "not forwarded" claim, run a control that shows what would have been sent.
- **Running the renderer tests in the image:** `docker/renderer/test_in_image.sh <image>`. Mount only the tests and `pyproject.toml`, and keep workdir `/app`, so the image's code is what gets tested. The browser tests `importorskip('playwright')`, so the script fails on any skip.
- **Compose v5:** a service that shares an image name with a service that has `build:` needs no `build:` of its own. The failed pull is not fatal; Compose builds the image and both use it.
- **`.env.example` is denied to agents for Read, grep and sed.** Leave its edits to the human, and do not write tests that read it.
- **This host's default address pools are exhausted** by other agents' networks, so `compose up` fails with "all predefined address pools have been fully subnetted". Pass a `/tmp` override that sets `networks.<name>.ipam.config[0].subnet`. Never prune other agents' networks.
- **WP-1h-style branches can lack WP-0b.** Run the WP-0b tests on a throwaway trial merge with `mig/integration`, then `git merge --abort` and delete the branch.

Related: [[compose-testing-traps]], [[image-verification-recipes]]
