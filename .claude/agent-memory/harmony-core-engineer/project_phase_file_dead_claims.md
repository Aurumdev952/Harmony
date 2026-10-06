---
name: phase-file-dead-claims
description: Phase files' "unused"/"dead" claims can be wrong; client calls via ZenClient omit the /api/ prefix so a grep for "/api/<route>" misses them
metadata:
  type: project
---

Verify every "unused" claim in a phase file before requesting a deletion. WP-0d listed `/api/timeout` as unused, but it is the server half of automatic sign-out. `web/client/util/timeoutSession.js` calls `ZenClient.post('timeout', {})`, and `ZenClient` prepends `/api/`. A grep for `api/timeout` finds no caller.

**Why:** deleting it would have silently disabled a security control. The lead confirmed this on 2026-10-04.

**How to apply:** for any Flask route, grep both the full path and the bare suffix as a string literal: `ZenClient\.(get|post)\(['"]<suffix>`, plus `$.getJSON`/`fetch`. Also check whether a "dead" resource is read at import time by another module. The Hadoop templates are loaded by `legacy_task_builder.py` class attributes, so the templates and that module must go together.
