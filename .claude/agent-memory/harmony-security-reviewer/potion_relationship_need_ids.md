---
name: potion-relationship-need-ids
description: Potion relationship needs (e.g. alert_notifications read via alertDefinition) use different id columns on the item path and the SQL list/read path; only the SQL path is reachable over HTTP
metadata:
  type: project
---

`HybridRelationshipNeed.__call__(item)` takes the id from `final_field.resource.manager.id_attribute`. That is the *owning* resource's id attribute, so for alert notifications it reads `AlertDefinition.id`. The list path and `manager.read(id)` both go through `PrincipalMixin._query`, which builds `need.fields[-1].target.manager._expression_for_ids`, keyed on the target's id column (`alert_definitions.authorization_resource_id`). That one is correct. Harmony never calls the item-level read `can(item)`, so the wrong key is latent.

**Why:** a harness that checks `permission.can(item)` with a stand-in parent missing either id attribute agrees with `is_authorized` vacuously. QA and the lead both read the item path as the production rule (WP-2b, 2026-10-04).
**How to apply:** when judging Potion-wiring tests or the WP-4e/5f ports, ask which path decides the HTTP outcome. Compile the SQL from `_query_filter_permission` to see it, and require stand-ins whose `id` and `authorization_resource_id` differ.
