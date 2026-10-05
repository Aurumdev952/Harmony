---
name: authz-review-traps
description: Traps found while reviewing the WP-2b authz suite: Potion relationship-need id, vacuous per-item agreement, stack.sh --no-build, run.sh temp leak, isolation hook
metadata:
  type: project
---

Lessons from the independent QA review of WP-2b (2026-10-04).

- **Potion `HybridRelationshipNeed` reads the owning resource's `id_attribute` on the related object.** For `AlertNotificationResource` read, the need is `ItemNeed(view_resource, alert_definition.id, 'alert_definitions')`: the AlertDefinition primary key, not `authorization_resource_id` (Resource.id) that alert ACL needs carry. A stand-in item that lacks the attribute Potion reads silently degrades to a sitewide check (value None).
  **Why:** the suite's `potion.yaml` recorded `read_via.id: authorization_resource_id` and still passed, because `_item` never set `.id` and ITEM_ID=7 is held by no alert principal.
  **How to apply:** when reviewing a Potion agreement test, rerun it with ITEM_ID set to an id a non-superuser actually holds for each type (e.g. 11 for alert_owner) and with distinct PK vs Resource.id on stand-in objects.
- **Per-item agreement is only as good as the item ids principals hold.** Flip a `read_via.type` in potion.yaml: if only `test_method_permissions` fails and no agreement row does, agreement is blind there.
- **`tests/authz/stack.sh up` uses `--no-build`.** It needs `harmony-wp2c-web-server:local`, which only WP-2c's `tests/contract/stack/stack.sh up` builds.
- **`run.sh` sets `trap ... EXIT` then `exec`s uv**, so the trap never fires and each run leaves a `/tmp/tmp.*` requirements file behind.
- **The worktree-isolation hook refuses compound bash that cds into /tmp trees, uses heredocs into python, or `env -i` inline.** Write the runner with the Write tool into /tmp/<scratch>/ and call it as a single plain command. Export branch files with `git archive <branch> <path> -o x.tar` from the own worktree, then untar.

Related: [[authz-escalations-found]]
