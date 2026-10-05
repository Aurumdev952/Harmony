---
wp: "0l"
title: "Match resource, role, group and user names exactly, never as patterns"
status: building
owner_role: "backend"
instances:
  - name: "backend-0l"
    files:
      - "web/server/routes/views/core.py"
      - "web/server/routes/views/resource.py"
      - "web/server/routes/views/users.py"
      - "web/server/routes/views/groups.py"
      - "web/server/routes/views/dashboard.py"
      - "web/server/routes/views/alerts.py"
      - "web/server/database/alerts.py"
      - "web/server/security/grants.py"
      - "web/server/api/user_api_models.py"
      - "web/server/api/group_api_models.py"
      - "tests/privilege_escalation/test_named_lookups.py"
      - "docs/modernisation/work/WP-0l-evidence/**"
      - "docs/modernisation/work/WP-0l.md"
  - name: "core-0l"
    files:
      - "web/server/data/data_access.py"
      - "tests/web/test_find_one_by_fields.py"
  - name: "qa-0l-tests"
    files:
      - "tests/privilege_escalation/test_exact_name_matching.py"
      - "tests/privilege_escalation/conftest.py"
      - "tests/web/test_exact_name_lookup.py"
      - "tests/authz/http/test_name_matching.py"
      - "tests/contract/cases/20-directory.json"
      - "tests/contract/cases/95-cleanup.json"
      - "tests/contract/recordings/user.update_roles.assign.json"
      - "tests/contract/recordings/group.update_roles.assign.json"
branch: "mig/WP-0l-exact-name-matching"
requirements: [INV-3, QA-1, QA-4]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0l: Match resource, role, group and user names exactly, never as patterns

Phase detail: [phase-0-security-and-subtraction.md, section 0l](../phase-0-security-and-subtraction.md). Added by [decision 0012](../decisions/0012-wp-0l-exact-resource-and-principal-name-matching.md). Depends on 0k.

## Plan

Units, in order. Each line names the change and the check that ends it. Every unit starts with a test that fails on `mig/integration` 7c34bca.

1. `find_one_by_fields(..., case_sensitive=False)` compares `func.lower(field) == func.lower(value)` instead of `field.ilike(value)`. The file is core's: requested below; core works it on `mig/WP-0l-exact-name-matching-core`, merged here when it lands. Check: a lookup of `a_b` never returns `axb`; `ABC` still finds `abc`.
2. Sharing (`update_user_resource_roles`, `update_group_resource_roles`, share removal in `_update_group_roles`) and the author grants on dashboard and alert creation use the resource object they were given; nothing re-finds a resource by its own name. Share removal acts on the exact principal. Check: `POST /api2/resource/<a_b>/roles` stores ACLs on `a_b` only, with `axb` created first; the creator of `a_b` becomes admin of `a_b`, not `axb`.
3. 403 bodies from `verify_acl_grants`, and the 404 type-mismatch body from `try_get_role_and_resource`, do not repeat resource names. Check: bodies carry no resource name; the audit line still does.
4. `try_get_user` and its callers (group membership, role membership, `lookup_author`, alert ownership transfer) match exactly, ignoring case. Check: adding `john_doe@…` to a group or role never adds `john.doe@…`; `John_Doe@…` still finds `john_doe@…`.
5. Tests for the three tracing notes: `get_resource_by_type_and_name` combining conditions with Python `and`; the legacy `POST /api2/{user,group}/<id>/roles` building `UserRoles`/`GroupRoles` with a `resource_id`; `PATCH /roles` with an empty body. Wrong-row and 500 outcomes are fixed here; the rest recorded below.
6. INV-3 table with the decision 0012 rows, and a live before/after on one stack.
7. Full checks: `tests/web`, `tests/privilege_escalation`, the `tests/authz` pure layer, lint, mypy, `ci/check_py38_syntax.py` on CPython 3.8.20, `ci/pytest_suites.sh`, `task_gate.py WP-0l`. Then `status: review`.

## Contract changes

None.

## Requests

- [x] core: in `web/server/data/data_access.py` `find_one_by_fields`, replace `query.filter(field.ilike(field_value))` with `query.filter(func.lower(field) == func.lower(field_value))` for string values when `case_sensitive=False` (blocks unit 1). Done by core on `mig/WP-0l-exact-name-matching-core` 7a5c600, merged here at 90a26f5.
- [x] qa: re-record the contract cases `user.update_roles.assign` and `group.update_roles.assign` (`PATCH /api2/{user,group}/<id>/roles` with a non-empty map), which now answer 400 instead of 500 (INV-3 row 11). Add a case for `POST /api2/{user,group}/<id>/roles` if wanted: it is 400 now, 500 before.
- [x] qa (qa-0l-tests): failing tests for paths A, B and D, and the WP-2b pins; merged at cc69345.

## Findings while building

- **Author grant on creation (new, not in decision 0012's table).** `make_author_dashboard_administrator` (`dashboard.py:265`), alert creation (`database/alerts.py:36`) and alert ownership transfer (`routes/views/alerts.py:94`) gave the author `dashboard_admin` or `alert_admin` by finding the new resource again by name with ILIKE. If a dashboard is created with slug `a_b` while `axb` exists, the author's admin ACL landed on `axb`, and the author had no ACL on their own dashboard (`test_creating_a_dashboard_makes_its_author_admin_of_that_dashboard`, failed on 7c34bca). Anyone who could create dashboards could take admin of an existing dashboard whose name the new slug matches as a pattern (`_` survives slugify). This is closed twice: core's exact match closes it, and `add_user_acl` now takes the `Resource` object.
- **Case-only pairs (the lead's request after core's merge).** Usernames and group names are unique only as stored, and resource names are not unique at all. For example, the slugs `a-b` and `a_b` both give the resource name `a_b`. `find_by_name` (`routes/views/core.py`) compares names equal ignoring case. When several rows match, the row spelled exactly that way wins if it is the only one; otherwise nobody matches and the request returns 404 with nothing written. It serves resource roles, resources by type and name (ACL grants), groups named in a share, and `try_get_user` (membership, `lookup_author`, alert transfer, share user names).
- **Shares named a holder in another case.** A share request with key `X@y` for an existing holder `x@y` set `X@y`'s roles, marked `x@y` for removal, and then stripped the same user. It also mailed them as a new recipient, which 500s outside a full app. Holders are now keyed by the principal, so the user keeps the roles the request names.
- **A share with an unknown name** returned 404 but had already committed the group-share removals of an empty `groupRoles` map (`delete_group_role(..., commit=True)`). Every name is now resolved before anything is written. The sitewide ACL is still written first, as before.

## Merging with WP-0k

WP-0k (`mig/WP-0k-configured-links-exact-usernames`, in review) changes `try_get_user` to `find_user_by_username`, which ranks active accounts first, and changes `resource.py:112`. On merge:
- keep WP-0k's `try_get_user` body (`find_user_by_username`), and drop the `find_by_name` import from `users.py` if nothing else uses it there;
- in `resource.py` keep this branch's `update_resource_roles`, with `try_get_user` as the user lookup;
- keep WP-0k's other `users.py` changes (`invite_users`, `get_anonymous_user`, `update_user_api_tokens`).

## Recorded, not changed

- `PATCH /api2/{user,group}/<id>/roles` with `{}` removes every role. This is the documented meaning of the route, and WP-0h pins it (`test_clearing_a_*_roles_keeps_the_roles`, `tests/authz/http/test_escalation.py:352`). Only a non-empty map is refused.
- In `POST /api2/resource/<id>/roles`, an empty `userRoles` map leaves every user's share alone, while an empty `groupRoles` map removes every group's share. The schema says an empty map removes all of them for both. Kept as it was.
- ACL payloads name their resource by `name`, although they carry a `$uri` that would identify the resource exactly. Resolving by `$uri` is left for the FastAPI port (WP-5c).
- Paths F and G (`settings.py:140`, `druid_context.py:130`, `scripts/create_user.py`) look up fixed keys or are operator-only. Core's change makes them exact; nothing else is needed.

## Log

One line per finished unit: `YYYY-MM-DD <instance> unit N: <what>; check: <command and result>`

- 2026-10-06 core-0l unit 1: `find_one_by_fields` with `case_sensitive=False` compares `lower(field) == lower(value)` (core 7a5c600, merged at 90a26f5). Check (core): `tests/web/test_find_one_by_fields.py` has 18 cases on SQLite and a throwaway Postgres; 14 failed before, including `a_b` returning the `axb` row. All 16 call sites were audited and none passes a pattern. tests/web 301, privilege_escalation 86, authz pure 4681 and golden 272 pass; lint, mypy and the 3.8 guard are clean.
- 2026-10-06 backend-0l units 2-5: `find_by_name`; sharing, removal and author grants on the `Resource` object; 403 and 404 bodies without resource names; `get_resource_by_type_and_name` filters on type; legacy role grants answer 400; alert transfer naming no user answers 404 (bf75d1c). Check: `tests/privilege_escalation/test_named_lookups.py` 23 pass, and 20 of them failed on 7c34bca, each for the reason it names (below). `tests/privilege_escalation` 109 passed, `tests/web` 301 passed and 1 xfailed, `uv run --locked mypy` clean (519 files), `ci/lint_python.sh origin/mig/integration` clean, `ci/check_py38_syntax.py` on cpython-3.8.20 found 0 problems in 869 files.
- 2026-10-06 qa-0l-tests: fail-first pins for paths A (sharing, and dashboard creation), B (user and group share removal, `_` and `%`), C (403 bodies) and D (group and role membership by username, look-alike-only 404) in `tests/privilege_escalation/test_exact_name_matching.py` (also adds `username=` to `make_user` and a `dashboard_creator` role in the shared conftest), `tests/web/test_exact_name_lookup.py` (data layer and the `get_resource_by_type_and_name` type filter) and live WP-2b pins in `tests/authz/http/test_name_matching.py`; check on 7c34bca: in-process 21 failed, 12 passed (every look-alike-first case fails, every named-first case passes); whole `tests/authz` with the live layer on a fresh stack 12 failed (all 12 new pins), 5264 passed; on bf75d1c: 33 in-process passed, whole `tests/authz` with the live layer 5276 passed.
- 2026-10-06 qa-0l-tests: contract `user.update_roles.assign` and `group.update_roles.assign` re-recorded 500 to 400 on a fresh stack from the WP-0l tree. This is the WP-0l behaviour: a non-empty legacy role map never wrote anything (it built `UserRoles`/`GroupRoles` with a `resource_id` they lack and a resource role id as `role_id`) and is now refused with `{message, status}`. The empty-map `*.update_roles.clear` cases are unchanged. No contract case covers `POST /api2/{user,group}/<id>/roles` (no client calls it). check: replay on that stack 233 passed, 1 failed (`storage.retrieve.unknown_slug` recorded 500, served 404: WP-0i's change, unrelated to WP-0l, not re-recorded here).

## Evidence

### Failing first (7c34bca plus the test file, before core's merge)

`uv run --locked pytest tests/privilege_escalation/test_named_lookups.py`: 20 failed and 3 passed. The tests that failed, and why:

| Test | Failure on 7c34bca |
|---|---|
| sharing a dashboard stores its ACLs on that dashboard | `a_b` holds no ACLs; both admin ACLs went to `axb` |
| sharing with a group stores its ACL on that dashboard | `a_b` holds no group ACL |
| creating a dashboard makes its author admin of it | the author has no ACL on the dashboard they created |
| a share naming a holder in another case keeps its roles | 500 |
| removing a user's share removes only that user's ACLs | `x.doe` lost its share and `x_doe` kept its share |
| a share naming an unknown user writes nothing | 404, but the group share was already removed |
| a refused ACL grant does not name the resource | 403 body: `... on DASHBOARD 'secret-…' needs ...` |
| a resource role of another type does not name the resource | 404 body: `Resource 'secret-…' is of type ...` |
| role membership by a look-alike username adds nobody | 200, and the look-alike was added |
| dashboard transfer from a look-alike username moves nothing | 204, and the look-alike's dashboard was transferred |
| alert transfer naming no user is not found (source, target) | 204, from or to the look-alike |
| a group named in another case than two groups is not found | 204, with one of the pair chosen |
| a user named in another case than two accounts is not found | 200, with one of the pair chosen |
| an ACL naming a resource two resources share is not found | 200, with one of the two chosen |
| a resource is found by type and name | the type was ignored |
| the legacy single-role POST is refused cleanly (user, group) | 500 `TypeError: 'resource_id' is an invalid keyword argument for UserRoles/GroupRoles` |
| a non-empty legacy role map is refused (user, group) | 500, same `TypeError` |

The three that passed on 7c34bca are the case-insensitive controls (role membership, dashboard transfer and alert transfer with an upper-cased username). The full run is in [WP-0l-evidence/named_lookups_on_7c34bca.txt](WP-0l-evidence/named_lookups_on_7c34bca.txt).

### Suites at bf75d1c

`ci/pytest_suites.sh`: all 13 suites pass. That includes authz 4681, privilege_escalation 109, web 301 (1 xfailed), golden 272, contract 60 and db 26 ([log](WP-0l-evidence/pytest_suites_bf75d1c.log)). `uv run --locked mypy` is clean. `ci/lint_python.sh origin/mig/integration` is clean. `uv run --no-project -p cpython-3.8.20 python ci/check_py38_syntax.py config data db log models graphql util web scripts tests/web tests/privilege_escalation` finds 0 problems in 869 files.

### Live before and after (one contract stack at a time, image `harmony-contract-web-server:b5eee49d3f44`)

`/tmp/wp0l_live.py` ran first against a stack on `git archive 7c34bca`, which was then torn down with its volumes, and then against a stack on `git archive bf75d1c`. It uses synthetic `@wp0l.invalid` accounts and X-Username login. `x` stands for the run's random tag. `create_user.py` on 7c34bca refused to create `x_doe@` once `x.doe@` existed, because its own ILIKE existence check matched (path G), so the `x_doe@` row was copied in SQL. Output: [WP-0l-evidence/live_before_after.txt](WP-0l-evidence/live_before_after.txt).

| Check | 7c34bca | bf75d1c |
|---|---|---|
| a non-admin creates dashboard `x_x` while admin's `xxx` exists | creator becomes `dashboard_admin` on `xxx`; `x_x` has no ACL | creator is admin of `x_x` only |
| admin shares `x_x` with `x.doe@` and `x_doe@` | 204; every ACL written on `xxx`; `x_doe@` resolved to `x.doe@` | 204; ACLs on `x_x`, one for each account |
| admin removes `x_doe@`'s share | 204; `x_x` untouched, `xxx` still lists `x.doe@` | 204; `x_doe@` removed, `x.doe@` kept |
| share naming `X_DOE@` (case only) | 204 (written on `xxx`) | 204; `x_doe@` keeps viewer |
| group `/users` with `x_member@` (only `x.member@` exists) | 200, `x.member@` added | 404, nobody added |
| group `/users` with `X.MEMBER@` | 200 | 200, `x.member@` added |
| share with group `PAIR-x` (`Pair-x` and `pair-x` exist) | 204, one of them chosen | 404, nothing written |
| share with group `pair-x` | 204 | 204, on `pair-x` |
| ACL `alert_admin` on dashboard `xxx`: body names `xxx` | 404, named | 404, not named |
| `POST /api2/user/<id>/roles`, `POST /api2/group/<id>/roles`, non-empty `PATCH /api2/user/<id>/roles` | 500 | 400 |
| alert transfer from `x_member@` (only `x.member@` exists) | 204 (from `x.member@`) | 404 |
| alert transfer from an unknown user | 500 | 404 |
| dashboard transfer from `x_member@` (`x.member@` authors `xxx`) | 204, `xxx` moved to admin | 404, author unchanged |

Contract replay on a fresh stack for each tree ([7c34bca](WP-0l-evidence/contract_replay_7c34bca.log), [bf75d1c](WP-0l-evidence/contract_replay_bf75d1c.log)): 233 and 231 passed. The only difference is `user.update_roles.assign` and `group.update_roles.assign`, which were 500 when recorded and are 400 now; qa re-recorded them. `storage.retrieve.unknown_slug` fails on both trees (recorded 500, served 404 since WP-0i) and is not related to this WP.

### INV-3 rows

Rows 1 to 5 are decision 0012's. Rows 6 to 13 are what this WP found and changed on purpose. Each needs acceptance by security and the human.

| # | Decision | Before (7c34bca) | After | Pinned by |
|---|---|---|---|---|
| 1 | Sharing `POST /api2/resource/<id>/roles` | ACLs written on the first resource of the type whose name the URL resource's name matches as a LIKE pattern | ACLs written on the resource in the URL | `test_sharing_a_dashboard_*`; qa path A |
| 2 | Removing a user's or group's share | could remove the share of a look-alike whose name matched as a pattern, and keep the named one's | removes exactly the holder spelled that way | `test_removing_a_users_share_removes_only_that_users_acls`; qa path B |
| 3 | A name with `_` or `%` and no exact match (share, group or role membership, ACL grant, transfer) | resolved to a matching row | 404, nothing written | `test_role_membership_by_a_look_alike_username_adds_nobody`, `test_dashboard_transfer_from_a_look_alike_*`, `test_alert_transfer_naming_no_user_*`; qa path D |
| 4 | Membership and transfers by username | pattern, case-insensitive | equal ignoring case | `*_ignores_case` |
| 5 | Case | case-insensitive | case-insensitive everywhere | `test_a_share_naming_a_holder_in_another_case_keeps_its_roles`, `*_ignores_case` |
| 6 | Author `dashboard_admin` on dashboard creation; `alert_admin` on alert creation and alert transfer | given on the first resource whose name the new name matches as a pattern | given on the new or transferred resource | `test_creating_a_dashboard_makes_its_author_admin_of_that_dashboard`, `test_alert_transfer_by_username_ignores_case` |
| 7 | A name equal ignoring case to several rows (usernames and group names unique only as stored; resource names not unique) | one of them, unordered | the exact spelling if only one row has it, else 404 with nothing written | `test_a_group_named_in_another_case_than_two_groups_*`, `test_a_user_named_*`, `test_an_acl_naming_a_resource_two_resources_share_*` |
| 8 | A share naming an existing holder in another case | the holder's roles were stripped (and a 500 from the access-granted email where it could not render) | the holder gets the roles named | `test_a_share_naming_a_holder_in_another_case_keeps_its_roles` |
| 9 | A share naming an unknown user or group | 404, but the removals implied by an empty `groupRoles` map were already committed | 404; only the sitewide ACL is written, as before | `test_a_share_naming_an_unknown_user_writes_nothing` |
| 10 | 403 from ACL grants on `PATCH /api2/{user,group}/<id>`; 404 for a resource role of another type | bodies name the resource | bodies name the type only; the audit line keeps id and name | `test_a_refused_acl_grant_*`, `test_a_resource_role_of_another_type_*` |
| 11 | `POST /api2/{user,group}/<id>/roles`; `PATCH .../roles` with a non-empty map | 500 (nothing written) | 400 (nothing written) | `test_the_legacy_single_role_post_*`, `test_a_non_empty_legacy_role_map_*`; contract `*.update_roles.assign` |
| 12 | `POST /api2/alert_definitions/transfer/username` naming a missing user | 500, or a transfer from or to a look-alike | 404 | `test_alert_transfer_naming_no_user_is_not_found` |
| 13 | `/api/is_authorized` with a `resourceName` (`get_resource_by_type_and_name`) | name only, the type ignored: a resource of another type with that name was checked under the asked type | name and type; several matches are 404 | `test_a_resource_is_found_by_type_and_name_not_by_name_alone` |

Unchanged: the empty `PATCH .../roles` still removes every role, and the asymmetric empty `userRoles` and `groupRoles` maps behave as before (see Recorded, not changed).

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
