---
wp: "0l"
title: "Match resource, role, group and user names exactly, never as patterns"
status: review
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
      - "web/server/routes/api.py"
      - "tests/privilege_escalation/test_named_lookups.py"
      - "tests/privilege_escalation/test_group_and_role_grants.py"
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

Round 2 (reviewer, QA and security verdicts at 3be8206). Each item is test-first with one commit, in the lead's order. Reviewer items:
- 2: one-dashboard transfer.
- 5: sitewide ACL after name resolution.
- 4: twin pins.
- 6: ACLs resolved by `$uri`, plus security's existence-oracle follow-up.
- 1: the merge-order pin and INV-3 row 15.
- 3: merge notes.
- 7: tracked evidence.
- 8: rows 3 and 6, with the `DELETE /roles` pin.
- 9: the twin-name 404 pin.
- 11: leftovers, with QA's row 11 item.

Security items 2 and 3 (the log line and the null `resourceType`) are also done. Reviewer item 10 (delete the `POST /roles` routes, giving 405) is optional and not done: the routes answer 400, and deleting them would change the contract inventory for no security gain.

## Contract changes

None.

## Requests

- [x] core: in `web/server/data/data_access.py` `find_one_by_fields`, replace `query.filter(field.ilike(field_value))` with `query.filter(func.lower(field) == func.lower(field_value))` for string values when `case_sensitive=False` (blocks unit 1). Done by core on `mig/WP-0l-exact-name-matching-core` 7a5c600, merged here at 90a26f5.
- [x] qa: re-record the contract cases `user.update_roles.assign` and `group.update_roles.assign` (`PATCH /api2/{user,group}/<id>/roles` with a non-empty map), which now answer 400 instead of 500 (INV-3 row 11). Add a case for `POST /api2/{user,group}/<id>/roles` if wanted: it is 400 now, 500 before.
- [x] qa (qa-0l-tests): failing tests for paths A, B and D, and the WP-2b pins; merged at cc69345.
- [ ] core (uniqueness rule, optional): make resource names unique per type, so an ACL that names a resource by name only (an empty `$uri`) can never be ambiguous. Since round 2 (reviewer item 6), ACLs with a `$uri` resolve by id, and the UI sends one; this does not block WP-0l. See Findings.

## Findings while building

- **Author grant on creation: path H in decision 0012 as amended, High for dashboards.** `make_author_dashboard_administrator` (`dashboard.py:265`), alert creation (`database/alerts.py:36`) and alert ownership transfer (`routes/views/alerts.py:94`) gave the author `dashboard_admin` or `alert_admin` by finding the new resource again by name with ILIKE. If a dashboard is created with slug `a_b` while `axb` exists, the author's admin ACL landed on `axb`, and the author had no ACL on their own dashboard (`test_creating_a_dashboard_makes_its_author_admin_of_that_dashboard`, failed on 7c34bca). Anyone who could create dashboards could take admin of an existing dashboard whose name the new slug matches as a pattern (`_` survives slugify). This is closed twice: core's exact match closes it, and `add_user_acl` now takes the `Resource` object.
- **Case-only pairs (the lead's request after core's merge).** Usernames and group names are unique only as stored, and resource names are not unique at all. For example, the slugs `a-b` and `a_b` both give the resource name `a_b`. `find_by_name` (`routes/views/core.py`) compares names equal ignoring case. When several rows match, the row spelled exactly that way wins if it is the only one; otherwise nobody matches and the request returns 404 with nothing written. It serves resource roles, resources by type and name (ACL grants), groups named in a share, and `try_get_user` (membership, `lookup_author`, alert transfer, share user names).
- **Shares named a holder in another case.** A share request with key `X@y` for an existing holder `x@y` set `X@y`'s roles, marked `x@y` for removal, and then stripped the same user. It also mailed them as a new recipient, which 500s outside a full app. Holders are now keyed by the principal, so the user keeps the roles the request names.
- **A share with an unknown name** returned 404 but had already committed the group-share removals of an empty `groupRoles` map (`delete_group_role(..., commit=True)`). Every name is now resolved before anything is written. The sitewide ACL was still written first at bf75d1c; since round 2 it is written only after every name is resolved (reviewer item 5).
- **QA observations, recorded and not changed here.**
  - The sharing route is `POST /api2/resource/<id>/roles`, not `PATCH .../users`; the pins and the INV-3 rows use it.
  - A dashboard's resource `label` lags one save behind its title. This is a finding for WP-5d.
- **Colliding resource names (security finding 1, Low, fails closed; request for WP-5c or core).** Any dashboard creator can pick a slug that becomes another dashboard's resource name: `v-x` and `v_x` both slugify to `v_x`. At bf75d1c, ACL grants naming `v_x` were ambiguous. Row 7 made them 404, so admins could not save a user or group holding an ACL on either dashboard. Since round 2, `verify_acl_grants` resolves an ACL by its resource `$uri` when it has one. The UI round-trips the `$uri` it read (`ItemLevelACL`, `Resource` serialize), so those saves succeed (`test_adding_a_member_to_a_group_sharing_a_twin_keeps_its_acl`). Only an ACL with an empty `$uri` and a colliding name is still a 404, and it fails closed. Making names unique per type (core, needs a migration and a decision on existing duplicates) would close that too. The human item for row 7 keeps this consequence.
- **Not repaired by this fix:** admin ACLs that were already stored on the wrong dashboard, including those from innocent name matches in the past. Decision 0012's amendment leaves a read-only audit per deployment to the human.
- **For decision 0012's consequence note (lead-owned; proposed text):** "A user or group update whose ACL names a resource the caller cannot see, and that the target does not already hold, answers the same 404 as for a resource that does not exist, whether the resource is named by `$uri` or by name. The refusal is still audited: a `Refused grant by '<caller>'` warning with the resource id and no name." Pinned by `test_an_acl_on_a_resource_the_caller_cannot_see_looks_like_no_resource` and `test_a_grant_on_a_hidden_resource_is_audited_by_id_only`, which failed before (no audit line). INV-3 row 7.

## Merging with WP-0k

Merge order: 0j, then 0k, then 0l, all at close-out. WP-0l merges only with or after WP-0k (INV-3 row 15). These notes were checked against WP-0k fdcad802 (PR #30) and WP-0j f7d8f678; the lead names the heads at close-out. On merge:
- **`users.py` `try_get_user`**: keep WP-0k's body, `return find_named_account(username, session)` (`web/server/security/usernames.py`). Do not use `find_user_by_username`, which ranks active accounts first.
  - `find_named_account` and `find_by_name` then hold the same rule twice, so make one call the other. For usernames they agree, because usernames are unique as stored, so at most one row has the exact spelling.
  - The simplest form is for `find_named_account(username, session)` to return `find_by_name(User, username, session, name_field='username')`.
  - Drop the `find_by_name` import from `users.py` if nothing else there uses it.
- **`resource.py`**: keep this branch's `update_resource_roles`, with `try_get_user` as the user lookup. WP-0k's `resource.py:112` (`find_named_account`) is on the line this branch rewrote. After taking this branch's `update_resource_roles`, drop WP-0k's now-unused `from web.server.security.usernames import find_named_account` in `resource.py` (`resource.py:21` on fdcad802), or ruff F401 fails the lint gate.
- **Other `users.py` changes**: keep WP-0k's (`invite_users`, `get_anonymous_user`, `update_user_api_tokens`).
- **`web/server/security/grants.py`, with WP-0j**:
  - Imports: keep `ItemNeed` and `User` from WP-0j, and `NotFound`, `ResourceTypeEnum`, `re` and the `core` imports (`find_by_name`, `resource_not_found`, `try_get_resource_role`, `try_get_resource_type`) from WP-0l.
  - Refusal helpers: WP-0j turns `refuse_grant` into `_refuse(action, ...)`, and WP-0l splits the audit line out of `refuse_grant` into `_audit_refusal(description, detail)` for the hidden-resource 404. Combine them into one logging helper, `_audit_refusal(action, description, detail)`, writing `'Refused %s by ...'`. `_refuse` logs through it and raises `Forbidden`, and `_resolve_acl` calls it with `'grant'`. The line `test_a_grant_on_a_hidden_resource_is_audited_by_id_only` expects starts `Refused grant`.
- **`no_mail` fixtures**: no edit needed. Both fixtures (qa's in `test_exact_name_matching.py` and this branch's in `test_named_lookups.py`) patch `url_for` and `deployment_url` with `raising=False`.
- **Strict xfail**: remove it from `test_signing_in_with_a_look_alike_username_never_acts_as_its_account`. Once WP-0k's login signs `user.username`, the test XPASSes, which fails a strict xfail.
- **Gates**: run all of `tests/privilege_escalation`, `tests/web`, `tests/authz` with the live layer, and the contract replay on the merged tree.

## Recorded, not changed

- `PATCH /api2/{user,group}/<id>/roles` with `{}` removes every role. This is the documented meaning of the route, and WP-0h pins it (`tests/privilege_escalation/test_group_and_role_grants.py::test_clearing_a_*_roles_keeps_the_roles`; live: `tests/authz/http/test_escalation.py::test_group_moderator_empty_role_map_unlinks_the_group_roles_and_keeps_them` and `::test_user_admin_empty_role_map_unlinks_the_user_roles_and_keeps_them`). A map that names no role (empty lists) also still removes every role; only a map naming a role is refused.
- In `POST /api2/resource/<id>/roles`, an empty `userRoles` map leaves every user's share alone, while an empty `groupRoles` map removes every group's share. The schema says an empty map removes all of them for both. Kept as it was.
- Paths F and G (`settings.py:140`, `druid_context.py:130`, `scripts/create_user.py`) look up fixed keys or are operator-only. Core's change makes them exact; nothing else is needed.

## Log

One line per finished unit: `YYYY-MM-DD <instance> unit N: <what>; check: <command and result>`

- 2026-10-06 core-0l unit 1: `find_one_by_fields` with `case_sensitive=False` compares `lower(field) == lower(value)` (core 7a5c600, merged at 90a26f5). Check (core): `tests/web/test_find_one_by_fields.py` has 18 cases on SQLite and a throwaway Postgres; 14 failed before, including `a_b` returning the `axb` row. All 16 call sites were audited and none passes a pattern. (Correction, round 2, reviewer item 1: the audit missed that the JWT session loader, `signal_handlers.py:324`, resolves the identity string that login signed in, and before WP-0k that is the typed username, checked at login with Flask-User's case-insensitive LIKE. With this change alone, `x.doe` typing `x_doe` and its own password acts as `x_doe`. WP-0l therefore merges only with or after WP-0k; INV-3 row 15.) tests/web 301, privilege_escalation 86, authz pure 4681 and golden 272 pass; lint, mypy and the 3.8 guard are clean.
- 2026-10-06 backend-0l units 2-5 (one commit, bf75d1c; the reviewer noted the bundling, and it stays because the branch history is not rewritten): `find_by_name`; sharing, removal and author grants on the `Resource` object; 403 and 404 bodies without resource names; `get_resource_by_type_and_name` filters on type; legacy role grants answer 400; alert transfer naming no user answers 404 (bf75d1c). Check: `tests/privilege_escalation/test_named_lookups.py` 23 pass, and 20 of them failed on 7c34bca, each for the reason it names (below). `tests/privilege_escalation` 109 passed, `tests/web` 301 passed and 1 xfailed, `uv run --locked mypy` clean (519 files), `ci/lint_python.sh origin/mig/integration` clean, `ci/check_py38_syntax.py` on cpython-3.8.20 found 0 problems in 869 files.
- 2026-10-06 qa-0l-tests: fail-first pins for paths A (sharing, and dashboard creation), B (user and group share removal, `_` and `%`), C (403 bodies) and D (group and role membership by username, look-alike-only 404) in `tests/privilege_escalation/test_exact_name_matching.py` (also adds `username=` to `make_user` and a `dashboard_creator` role in the shared conftest), `tests/web/test_exact_name_lookup.py` (data layer and the `get_resource_by_type_and_name` type filter) and live WP-2b pins in `tests/authz/http/test_name_matching.py`; check on 7c34bca: in-process 21 failed, 12 passed (every look-alike-first case fails, every named-first case passes); whole `tests/authz` with the live layer on a fresh stack 12 failed (all 12 new pins), 5264 passed; on bf75d1c: 33 in-process passed, whole `tests/authz` with the live layer 5276 passed.
- 2026-10-06 qa-0l-tests: contract `user.update_roles.assign` and `group.update_roles.assign` re-recorded 500 to 400 on a fresh stack from the WP-0l tree. This is the WP-0l behaviour: a non-empty legacy role map never wrote anything (it built `UserRoles`/`GroupRoles` with a `resource_id` they lack and a resource role id as `role_id`) and is now refused with `{message, status}`. The empty-map `*.update_roles.clear` cases are unchanged. No contract case covers `POST /api2/{user,group}/<id>/roles` (no client calls it). check: replay on that stack 233 passed, 1 failed (`storage.retrieve.unknown_slug` recorded 500, served 404: WP-0i's change, unrelated to WP-0l, not re-recorded here).
- 2026-10-06 backend-0l security round 1, items 2 and 3 (25ec859): the cleared-roles log line names the username only; `get_resource_by_type_and_name` refuses a missing or non-string type or name with 400. Check: both new pins failed before (`'NoneType' object has no attribute 'upper'`; log line carried names and `IP:127.0.0.1`). `ci/pytest_suites.sh` all 13 suites pass (privilege_escalation 137, web 309); mypy clean; the 3.8 guard finds 0 problems. Lint is clean on every file except security's `WP-0l-evidence/security/probe.py` (round 2 unit 7).
- 2026-10-06 backend-0l unit 6: INV-3 table (rows 1 to 13, with row 6 being decision 0012's amended path H) and the live before and after on one contract stack at a time (7c34bca, then bf75d1c). Merged qa fe2bb60 and `mig/integration` 290cd65 (cf395af). Check on cf395af: `ci/pytest_suites.sh` all 13 suites pass, including privilege_escalation 134, web 309 and authz 4681 ([log](WP-0l-evidence/pytest_suites_cf395af.txt)); contract replay on a fresh stack passes 234/234; `ci/lint_python.sh origin/mig/integration` clean; mypy clean; the 3.8 guard finds 0 problems in 871 files.
- 2026-10-06 backend-0l round 2, one commit per item. Every pin failed before its fix, on the tree named, for the reason given:
  - Item 2, 3ceb8b2: one-dashboard transfer. Before, the dashboard did not move. Row 14.
  - Item 5, a2cf4269: sitewide ACL after name resolution. Before, the sitewide ACL row was stored on a 404. Row 9.
  - Item 4, 58933475: twin pins. On 90a26f5 all three failed. Evidence: [twin_pins_on_90a26f5.txt](WP-0l-evidence/twin_pins_on_90a26f5.txt).
  - Item 6, aed7d825: ACLs by `$uri`. Before, 404 instead of 200, 403 and 400.
  - Security's oracle follow-up, 21221343: a resource the caller cannot see answers the same 404 as a missing one. Before, it answered 403. Row 7.
  - Item 1, a14b76d9: merge-order pin. On this branch alone the sign-in gets 200 (strict xfail); on 290cd65 it passes. Row 15.
  - Item 3, 8b681706: merge notes against WP-0k fa44242.
  - Item 7, 277ee609: evidence tracked as `.txt`; `probe.py` exempt from lint.
  - Item 8, 3d560908: `DELETE /roles` pin, which fails on 7c34bca. Rows 3 and 6.
  - Item 9, c9685a49: a name two resources of a type share finds neither. Fails on 90a26f5.
  - Item 11 and QA item 4, d78e755e and 8d9dafd4: a map naming no role still strips. Passes on 7c34bca, failed on the previous head. Row 11 rewritten; leftovers removed.
  - QA merged: d975a521, cb4f3906 and 42555666.
  
  Check on a58c77fc: `ci/pytest_suites.sh` all 13 suites pass, including privilege_escalation 158 with 1 xfailed, web 309 and authz 4681 ([log](WP-0l-evidence/pytest_suites_round2.txt)). Contract replay on a fresh stack passes 234/234 ([log](WP-0l-evidence/contract_replay_round2.txt)). Lint and mypy are clean; the 3.8 guard finds 0 problems in 871 files.
- 2026-10-06 backend-0l round 3 (QA r2 lows, reviewer r2 F1 to F4). Every pin failed before its fix:
  - 3b8f30de, QA lows:
    - A refused grant on a hidden resource is audited by resource id only; before, it left no audit line.
    - `/api/authorization` and `/api/authorization_multi` answer a JSON 400 for a null or non-string `resourceType`; before, HTML 400.
    - Merge notes updated for the `grants.py` conflict with WP-0j.
    - The `no_mail` fixture tolerates WP-0k.
  - 892174f3, F1: merged qa d6ca1a35 (live row-10 and row-7 pins).
  - d370e6fa, F2: group sharing on the second of two same-named resources. On 90a26f5 the ACL landed on the first ([log](WP-0l-evidence/group_twin_pin_on_90a26f5.txt)). Row 1.
  - 89762102, F3: role names resolved before any write. Before, a 404 left the sitewide ACL stored. Row 9.
  - F4: merge notes for WP-0k fdcad802, including dropping the unused `find_named_account` import in `resource.py`.
  - The decision 0012 consequence text is proposed under Findings (the decision file is lead-owned).

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

`ci/pytest_suites.sh`: all 13 suites pass. That includes authz 4681, privilege_escalation 109, web 301 (1 xfailed), golden 272, contract 60 and db 26 ([log](WP-0l-evidence/pytest_suites_bf75d1c.txt)). `uv run --locked mypy` is clean. `ci/lint_python.sh origin/mig/integration` is clean. `uv run --no-project -p cpython-3.8.20 python ci/check_py38_syntax.py config data db log models graphql util web scripts tests/web tests/privilege_escalation` finds 0 problems in 869 files.

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

Contract replay on a fresh stack for each tree ([7c34bca](WP-0l-evidence/contract_replay_7c34bca.txt), [bf75d1c](WP-0l-evidence/contract_replay_bf75d1c.txt)): 233 and 231 passed. The only difference is `user.update_roles.assign` and `group.update_roles.assign`, which were 500 when recorded and are 400 now; qa re-recorded them. `storage.retrieve.unknown_slug` fails on both trees (recorded 500, served 404 since WP-0i) and is not related to this WP. The re-recording on `mig/integration` 290cd65 fixes it.

The merged head cf395af contains qa fe2bb60 and `mig/integration` 290cd65. Its production code is identical to bf75d1c (`git diff bf75d1c cf395af -- web models util config db data` is empty), so the live table above stands for it. On a fresh stack for cf395af, contract replay passes all 234 cases ([log](WP-0l-evidence/contract_replay_cf395af.txt)).

### INV-3 rows

Rows 1 to 5 are decision 0012's. Rows 6 to 13 are what this WP found and changed on purpose. Each needs acceptance by security and the human.

| # | Decision | Before (7c34bca) | After | Pinned by |
|---|---|---|---|---|
| 1 | Sharing `POST /api2/resource/<id>/roles` | ACLs written on the first resource of the type whose name the URL resource's name matches as a LIKE pattern | ACLs written on the resource in the URL | `test_sharing_a_dashboard_*`, `test_sharing_the_second_twin_with_a_group_lands_on_it`; qa path A |
| 2 | Removing a user's or group's share | could remove the share of a look-alike whose name matched as a pattern, and keep the named one's | removes exactly the holder spelled that way | `test_removing_a_users_share_removes_only_that_users_acls`; qa path B |
| 3 | A name with `_` or `%` and no exact match (share, group or role membership, ACL grant, transfer, `DELETE /api2/{user,group}/<id>/roles`) | resolved to a matching row; `DELETE .../roles` removed the role on the look-alike resource | 404, nothing written | `test_deleting_a_role_on_a_look_alike_name_removes_nothing`, `test_role_membership_by_a_look_alike_username_adds_nobody`, `test_dashboard_transfer_from_a_look_alike_*`, `test_alert_transfer_naming_no_user_*`; qa path D |
| 4 | Membership and transfers by username | pattern, case-insensitive | equal ignoring case | `*_ignores_case` |
| 5 | Case | case-insensitive | case-insensitive everywhere | `test_a_share_naming_a_holder_in_another_case_keeps_its_roles`, `*_ignores_case` |
| 6 | Decision 0012 amendment, path H: creating a dashboard or an alert, or transferring a dashboard (one or in bulk) or an alert, makes the author or new owner admin of exactly that resource | `dashboard_admin` or `alert_admin` given on the first resource whose name the new name matches as a pattern; for dashboards, `xxx` instead of the author's own `x_x` (live check above) | given on the new or transferred resource | `test_creating_a_dashboard_makes_its_author_admin_of_that_dashboard`, `test_creating_a_twin_*`, `test_transferring_a_twin_*`, `test_transferring_a_dashboard_moves_only_that_dashboard`, `test_alert_transfer_by_username_ignores_case` |
| 7 | A name equal ignoring case to several rows (usernames and group names unique only as stored; resource names not unique) | one of them, unordered | the exact spelling if only one row has it, else 404 with nothing written. ACLs in user and group updates resolve by their resource `$uri` when present (round 2), so only an ACL with an empty `$uri` naming colliding slugs (`v-x`, `v_x`) is a 404 (see Findings). An ACL grant on a resource the caller cannot see, which the target does not already hold, gets the same 404 as one that does not exist, whether named by `$uri` or by name. Before, it was a 403, which told the caller the resource exists (security's review of aed7d825). Grants on visible resources the caller cannot share stay 403. The hidden-resource refusal is audited by resource id only | `test_a_group_named_in_another_case_than_two_groups_*`, `test_a_user_named_*`, `test_an_acl_naming_a_resource_two_resources_share_*`, `test_adding_a_member_to_a_group_sharing_a_twin_keeps_its_acl`, `test_an_acl_uri_*`, `test_an_acl_on_a_resource_the_caller_cannot_see_looks_like_no_resource`, `test_a_grant_on_a_hidden_resource_is_audited_by_id_only` |
| 8 | A share naming an existing holder in another case | the holder's roles were stripped (and a 500 from the access-granted email where it could not render) | the holder gets the roles named | `test_a_share_naming_a_holder_in_another_case_keeps_its_roles` |
| 9 | A share naming an unknown user or group, a look-alike with no exact match, or a resource role that does not exist or is for another resource type | 404, but the sitewide ACL in the body was already committed, and so were the removals implied by an empty `groupRoles` map | 404 with nothing written; the sitewide ACL is written only once every user, group and role name is resolved | `test_a_share_naming_an_unknown_user_writes_nothing`, `test_a_share_naming_no_one_leaves_the_sitewide_acl_alone`, `test_a_share_naming_a_role_it_cannot_grant_writes_nothing` |
| 10 | 403 from ACL grants on `PATCH /api2/{user,group}/<id>`; 404 for a resource role of another type | bodies name the resource | bodies name the type only; the audit line keeps id and name | `test_a_refused_acl_grant_*`, `test_a_resource_role_of_another_type_*` |
| 11 | `POST /api2/{user,group}/<id>/roles`; `PATCH .../roles` with a map naming a role | `POST` for an ACL the target did not hold: 500 (it built `UserRoles`/`GroupRoles` with a `resource_id` they lack), nothing written; `POST` for one already held: 200, no-op; a `PATCH` map naming a role: 500 | 400, nothing written. A `PATCH` map naming no role (`{}`, or empty role lists) still removes every role, 200, as before | `test_the_legacy_single_role_post_*`, `test_a_non_empty_legacy_role_map_*`, `test_a_legacy_role_map_naming_no_role_still_removes_every_role`; contract `*.update_roles.assign` |
| 12 | `POST /api2/alert_definitions/transfer/username` naming a missing user | 500, or a transfer from or to a look-alike | 404 | `test_alert_transfer_naming_no_user_is_not_found` |
| 13 | `/api/authorization` and `/api/authorization_multi` with a `resourceName` (`get_resource_by_type_and_name`) | name only, the type ignored: a resource of another type with that name was checked under the asked type; a null `resourceType` was a 500 | name and type; several matches are 404; a missing or non-string type with a name is a JSON 400 (`{success: false, data: {code: BAD_REQUEST, message}}`), on both routes | `test_a_resource_is_found_by_type_and_name_not_by_name_alone`, `test_a_name_two_resources_of_the_type_share_finds_neither`, `test_an_authorization_check_without_a_resource_type_is_a_json_400`, `test_an_authorization_check_naming_an_unknown_type_is_not_found` |
| 14 | Path E, `POST /api2/dashboard/<id>/transfer` and `/transfer/username` (one dashboard). Pre-existing since 4cbb72e, found by the reviewer | `api_transfer_dashboard_ownership` passed the dashboard as the old author, so every dashboard whose `author_id` equalled the dashboard's id moved to the new author, and the dashboard itself did not move. A user with no roles who could transfer their own dashboard took another user's dashboards (High) | only the dashboard in the URL moves, and the new author gets `dashboard_admin` on it | `test_transferring_a_dashboard_moves_only_that_dashboard` |
| 15 | Merge order (reviewer item 1). Sign-in with a look-alike username and one's own password | on 290cd65 the session resolves the typed string by LIKE to the signer's own account (no takeover) | on this branch alone, the session resolves it exactly to the look-alike's victim, which is a takeover (`200` on a victim-only route). With WP-0k merged, login signs `user.username`, so it is the signer's own account again (`401` per the reviewer's trial merge). WP-0l must merge with or after WP-0k | `test_signing_in_with_a_look_alike_username_never_acts_as_its_account`, strict xfail until WP-0k merges; passes on 290cd65 |

Unchanged: the empty `PATCH .../roles` still removes every role, and the asymmetric empty `userRoles` and `groupRoles` maps behave as before (see Recorded, not changed).

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-06 qa r3 at a244f33f: all round-2 items and reviewer F2/F3 closed with fail-first pins; head 13 suites green, live authz 5278/0; joint tree (b1aa182f + 0j f7d8f678 + 0k fdcad802 + 0l, trial 46bfcb79 at /tmp/qa-0l-r3-joint) 16 suites green (privilege_escalation 283, web 627+1), live authz 5420/0, contract replay 234/234, lint, 3.8 guard, mypy clean. Info: /api/authorization 500 when resourceType key missing (pre-existing); Postgres-backed web cases may skip under load, compare skip counts at close-out. |
| reviewer | approved | 2026-10-06 rev r3 at a244f33f: F1-F4 and qa lows closed; 18 mutants all caught (name re-find for users and groups, first-of-several, four oracle variants, $uri ignored, role-name check skipped or users-only, sitewide-first, bulk transfer, empty legacy map, case-sensitive matching, audit line, JSON 400); four-way tree (b1aa182f + 0j f7d8f678 + 0k fdcad802 + 0l) offline suites green, mypy, 3.8 guard clean. Merge only with 0k after 0j, strict xfail removed at the merge; 0j's test_rename_and_reset.py needs 0k's merge-with-0j patch (url_for in views.admin removed; create_user_access_token takes a User). |
| security | approved | 2026-10-06 sec r2 at 9b3107af (static: code, round-2 pins, semgrep 0 findings; no live stack this round, live confirmation left to qa-0l-r2): transfer moves only the URL dashboard; sitewide ACL written after principal resolution; ACLs by $uri with 404 parity for missing and unseen; log line names username only; null resourceType 400. Lows for WP-5c: share returns 404 after committing the sitewide ACL on a bad role name; legacy PATCH /roles empty map strips roles with only edit_resource (user_admin). Rows 7, 9, 11, 14 accept; row 15 accept only as hard constraint: merge with or after WP-0k. |
