---
name: druid-exposure-ruling
description: Druid HTTP ports are unauthenticated with JavaScript on; WP-0b ruling (2026-10-04) required bind addresses now; no WP schedules Druid authentication
metadata:
  type: project
---

Druid 0.23 in `druid_setup` loads no authenticator (`druid_extensions_loadList` has no druid-basic-security) and runs `druid_javascript_enabled=true`. Anyone who reaches 8081/8082/8888 can read every datasource (bypassing Harmony's per-user query policies, which only web applies), submit or kill tasks, and run JavaScript in the JVM. Harmony itself only uses 8081, 8082 and 8888 (`db/druid/config.py`); in single mode 8083, 8091 and 8100-8105 have no external consumer.

On 2026-10-04 the WP-0b security review ruled: do not accept until WP-8a; require `${DRUID_BIND_ADDRESS:?}`-style binding now and unpublish the internal ports, and document a host firewall.

**Why:** WP-8a only disables JavaScript, and cannot before Harmony's own `js_formulas` go, so it leaves unauthenticated read/write. No WP in SPEC section 5 adds Druid authentication.

**How to apply:** At WP-8a/8b review, check that Druid auth (or an authenticating proxy) has been planned, and re-run the port render (`docker compose config` over all four Druid files) to make sure nothing is bound to 0.0.0.0. Related: [[jwt-loader-semantics]].
