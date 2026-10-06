---
name: live-before-after-contract-stack
description: How to run a live before/after on the contract stack without network or image rebuilds, and the traps that cost reruns in WP-0l (2026-10-06)
metadata:
  type: reference
---

- **No rebuild offline.** `tests/contract/stack/stack.sh up` always runs `docker build`, which misses the layer cache from a fresh tree and then fails with no internet.
  - `git archive <rev> | tar -x -C /tmp/<dir>`.
  - In that copy only, replace the `build_images` line under `up)` with `export CONTRACT_WEB_IMAGE=harmony-contract-web-server:<hash>`. The hash is `cat requirements.txt requirements-web.txt docker/web/Dockerfile_web-server | sha256sum | cut -c1-12`.
  - Run that copy's `stack.sh`; the source is bind-mounted from that tree.
  - Run before (base) and after (head) one at a time on the same `CONTRACT_PROJECT`, with `down` in between; `down` removes the volumes.
- **Replay needs a fresh stack.** A second replay, or one run after your own live script, fails on list cases ("acls array is empty in recording, non-empty now"). Bring a stack up, replay once, and tear it down. Compare the base and head failure sets, not the raw counts.
- **Look-alike pairs must be stored look-alike first.** An unordered `first()` over ILIKE returns the row stored first. Create `x.doe` first, then `x_doe`.
  - On a pre-fix tree, `scripts/create_user.py` refuses `x_doe` once `x.doe` exists, because its own ILIKE existence check matches. Copy the second row in SQL: `insert into "user" ... select ... from "user" where username = 'x.doe'`.
  - `UPDATE`-renaming a row moves it in heap order, so renaming does not give you a look-alike-first pair.
- **Never print a failing subprocess's argv.** It carried the run's synthetic password into the transcript once. Report only the command name and stderr.
- **SQLAlchemy and Python `and`.** `filter(A == x and B == y)` keeps only the first clause, because `bool()` of an `==` expression against a bind parameter is False. The type condition in `get_resource_by_type_and_name` was dropped silently for years.

- **Late blueprints on the session app.** The `tests/privilege_escalation` app has already served requests, so registering a new blueprint on it (for example `ApiRouter` for `/api/authorization`) fails with "A setup function was called after the first request". Call the handler inside `app.test_request_context(..., headers={'X-Username': ..., 'X-Password': ...})` and assert the exception instead.
- **Reviewers' standing checks on authz fixes (WP-0l round 2, 2026-10-06):**
  - Resolving an id or `$uri` before the permission check creates an existence oracle (404 missing versus 403 hidden). Answer the same 404, with the same body, for both.
  - Prove "fail first" for mutation-style pins on the intermediate tree (core's change only), not only on the base.
  - A pin that must fail until a sibling WP merges is a strict xfail, plus a merge note to remove it.

Related: [[potion-route-test-harness]], [[backend-testing-traps]]
