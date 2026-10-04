---
name: renderer-chromium-sandbox
description: Hardening traps for the Playwright/Chromium renderer container (WP-1h) - cap_drop ALL breaks the sandbox, init needed, env.example and network pool traps
metadata:
  type: project
---

- **cap_drop ALL plus Playwright's seccomp profile kills Chromium.** Docker evaluates the profile's `includes.caps` rules against the container's capabilities. `chroot` is allowed only with CAP_SYS_CHROOT, so the zygote dies with `Check failed: sys_chroot("/proc/self/fdinfo/") == 0`. Fix: `cap_add: [SYS_CHROOT]`. A non-root pwuser still has CapEff 0, and its bounding set holds only SYS_CHROOT. Keep the profile byte-identical to upstream so its sha256 can be audited.
  **Why:** the WP-1h proposal and its unit-5 check only probed /healthz under cap_drop ALL and never launched a browser, so the breakage went unnoticed.
  **How to apply:** prove any browser-container hardening with a real launch (`chromium_sandbox=True`, then `page.pdf()`) or with the in-image suite under exactly the Compose flags.
- **Use `init: true` for any service whose PID 1 spawns browsers.** Each closed Chromium leaves about 2 zombies on a Python PID 1, and they count against pids_limit.
- **`.env.example` is denied to agents for Read, grep and sed.** Leave its edits to the human, and do not write tests that read it.
- **This host's default address pools are exhausted** by other agents' networks, so `compose up` fails with "all predefined address pools have been fully subnetted". Pass a `/tmp` override that sets `networks.<name>.ipam.config[0].subnet`. Never prune other agents' networks.
- **WP-1h-style branches can lack WP-0b.** Run the WP-0b tests on a throwaway trial merge with `mig/integration`, then `git merge --abort` and delete the branch.

Related: [[compose-testing-traps]], [[image-verification-recipes]]
