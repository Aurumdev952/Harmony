---
name: review-legacy-flask-auth
description: Traps and probe recipes for reviewing legacy Flask auth, JWT session and query-policy WPs (learned on WP-0c) - unit interactions on existing sessions, dead plumbing, AST guard gaps
metadata:
  type: project
---

Learned reviewing WP-0c on 2026-10-04.

- **Check how units combine on existing sessions.** WP-0c signed `remember_me` into the JWT (a token without the claim reads as "not remembered", described as "matches today"). It also made `/api/timeout` really clear `accessKey`. Each unit was right on its own. Together, every pre-deploy "Remember me" session is signed out at its first 30-minute idle, because `AUTOMATIC_SIGN_OUT_KEY` ('keep_me_signed_in') defaults to True. Before the WP, a timeout only bounced the user through `/login`, which redirects authenticated users straight back. Probe: mint a token with the old claim shape via `create_access_token(user_claims={'needs':['*'],'query_needs':['*']})`, set it as the cookie, POST `/api/timeout`, then hit an authenticated route.
- **Dead plumbing can fake a behaviour change.** The old `ApiRouter.__init__` captured `druid_context.row_count_lookup`, but `get_field_summary` read `druid_context.row_count_lookup` per request anyway. Read the old call path before claiming a datasource or cache difference. `druid_context.row_count_lookup` is `lru_cache(1)` per datasource (`SiteDruidDatasource` hashes by value). `data_time_boundary` is a new object per access in the web app.
- **SEC-4 AST guard** (`tests/web/test_no_raw_queries_from_routes.py`): import `_scan` and feed it snippets. It is lexical and covers one hop only. It misses:
  - `getattr(current_app, 'druid_context')`;
  - the classmethod system client `db.druid.query_client.DruidQueryClient.run_query` / `run_pydruid_query`, and `DruidQueryClient_(cfg)`;
  - direct `RowCountLookup(...)` / `DataTimeBoundary(...)`;
  - helpers outside `routes/` and `api/` (for example `routes/index.py` `data_status` calls `web/server/data/status_page.py`).
- **The run_query policy only lives in `query.query_filter`.** `GroupByQueryBuilder.prepare()` runs `ExactUniqueCountAggregation.modify_query`, which rebuilds the inner filter from `dimension_filter` and sets the outer one to None, so the policy is dropped. This is latent: no config uses `ExactUniqueCountCalculation` today. Any test of policy injection should assert on `prepare().query_dict`, not on `query.query_filter`.
- `db/druid/util.py` monkeypatches pydruid: `Filter & EmptyFilter` returns the left filter, and `build_filter` turns `EmptyFilter` into `None`. Run a probe on real `harmony_demo` config before reasoning about filter shapes.
- The interrogate `model` field accepts only aliases (opus, fable, sonnet), not `claude-opus-5` style names.

**Why:** the session interaction was the most user-visible change in WP-0c, and the WP's difference table missed it.
**How to apply:** for any auth or session WP, list each unit's "missing claim or flag = old behaviour" default, then re-check it against every other unit's new behaviour. Related: [[review-traps]].
