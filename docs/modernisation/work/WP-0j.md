---
wp: "0j"
title: "Refuse username changes and password resets that reach a higher-privileged account"
status: review
owner_role: "backend"
instances:
  - name: "backend-0j"
    files:
      - "web/server/api/user_api_models.py"
      - "web/server/security/grants.py"
      - "web/server/potion/managers.py"
      - "web/server/api/dashboard_api_models.py"
      - "tests/privilege_escalation/test_rename_and_reset.py"
      - "tests/privilege_escalation/test_group_and_role_grants.py"
      - "docs/modernisation/work/WP-0j.md"
  - name: "qa-0j-pins"
    files:
      - "tests/authz/http/test_account_handover.py"
branch: "mig/WP-0j-rename-reset-guard"
requirements: [INV-3, QA-1, QA-4]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0j: Refuse username changes and password resets that reach a higher-privileged account

Phase detail: [phase-0-security-and-subtraction.md, section 0j](../phase-0-security-and-subtraction.md). Added by [decision 0005](../decisions/0005-wp-0j-account-takeover-via-rename-and-reset.md) after the WP-0h security round 2 confirmed H5 live. Depends on WP-0h, which is still in review: this branch started from `mig/WP-0h-privilege-escalations` at `a615058` and merged its round 3 (`b094556`), then `488e482` and `mig/integration` `61db9f8`. It reuses WP-0h's harness (`tests/privilege_escalation`) and `web/server/security/grants.py`.

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Claim; read decision 0005, phase 0j, the user Potion resource, `send_reset_password` and the WP-0h grant helpers. Check: this file.
2. Failing tests on the WP-0h harness (`tests/privilege_escalation/test_rename_and_reset.py`): `manager` + `user_admin` renaming, and resetting the password of, an admin-through-group user, plus the other grants a target can hold beyond the caller (a role, a group, an ACL, a query-policy role, an exporting role); equal-or-lesser targets still rename and reset; superusers unchanged; the mailer is a stub. Check: the refusal tests fail on `a615058` for the reason H5 gives (200/204, username changed, mail handed to the stub); the unchanged-behaviour tests pass there.
3. The guard in `grants.py`, called from `PATCH /api2/user/<id>` (only when `username` changes) and `POST /api2/user/<id>/reset_password`. Check: the new tests pass, the WP-0h tests still pass; a mutation pass over every clause of the guard; CI lint and mypy.
4. Merge WP-0h round 3, then the CI gates on the merged tree. Check: `ci/lint_python.sh`, `uv run --locked mypy`, `ci/pytest_suites.sh`.
5. Decide the optional `UserResourceManager` change with a note for security; INV-3 table; human acceptance item; Request to qa for the WP-2b pins. Check: this file.
6. `pstack:interrogate` on the guard; triage findings. Then `status: review`.

Round 2 (reviewer round 1 findings, then decision 0010), one commit each:

7. Pin the `all` in `_holds_acl` and the resource id with two higher targets; mutants `all` to `any` and resource id ignored. Check: they fail on the new file and pass on the round-1 one.
8. Pin that a rename is judged on the stored user and writes nothing: drop the group that makes the target hold more and change `lastName` in the same body. Check: the body-judging mutant fails.
9. Decision 0010: `UserResourceManager` hides administrators through a group from every non-superuser identity. Tests first for the destructive routes, the list, superusers, ordinary users and narrowed tokens; INV-3 rows 3 to 5; human item; residuals. Check: the new tests fail at `b090396` on status codes, pass after; WP-0h harness green; mutants.
10. Ordering and exact comparison: `manager` alone, a rename plus an unheld role, a case-only rename. Check: three mutants fail.
11. Breadth note: narrowed admin tokens, alert authors, `user_moderator`, what a bare reset mails. Check: this file.
12. One held-role-ids and one member-group-ids helper in `grants.py`, used by every caller; ACL needs built from `current_user`. Check: harness green, mypy, the full mutation table.
13. The over-50-character 500 under Findings (WP-5d), the QA-4 evidence line, then the gates (3.9 and CPython 3.8.20, lint, mypy, 3.8 syntax guard, trial merge with `mig/integration` and `ci/pytest_suites.sh`, `task_gate.py`). Merge qa's pin branch when the lead reports its head.

### How H5 works

`PATCH /api2/user/<id>` is gated by `edit_user` on site plus Potion's `edit_resource` on user; the seeded holders of both are `manager` + `user_admin`. WP-0h checks what the body grants, and resending the target's current groups is allowed, so a rename keeps a group carrying the admin role. `POST /api2/user/<id>/reset_password` is gated by `reset_password` on user (`user_admin`, `user_moderator`); `send_reset_password(user.username)` stores a reset token and mails the link to the username. Rename to an address the caller reads, then reset: the caller sets the admin's password. `UserResourceManager` hid only users holding the admin role directly, so an admin through a group was reachable. Since decision 0010 it hides both (below).

### The rule

Administrators, direct or through a group, are hidden from every non-superuser identity (below), so both routes, like every user route, answer 404 for them before any check here. The guard decides for every other target.

`web/server/security/grants.py`, `verify_may_rename` and `verify_may_reset_password`:

- A caller whose identity is a superuser (`current_user_is_superuser`, as in WP-0h) is not checked.
- Otherwise the target must hold nothing the caller's account does not:
  - **roles**, by id, direct or through a group. The admin role is never held by a non-superuser identity (a narrowed token on an admin account), as in `held_roles_from_uris`. Query policies and data export come only from roles, so they are covered here;
  - **group memberships**, by id. Membership is a grant on its own: it decides which group item routes the account reaches;
  - **user ACLs**, by what they allow: every need the ACL builds must be in the caller's account needs, on that resource or sitewide (`ItemNeed(permission, None, type)`), the same cover `is_authorized` applies. A group's ACLs come with the group, so they are covered by membership.
- The rename check runs only when the body's `username` differs from the stored one, after Potion's `edit_resource` check and before any grant check or write. Profile edits that keep the username are unchanged.
- The reset check runs inside `AuthorizedOperation('reset_password', 'user', id)`, so a caller without that permission still gets 401 and no audit line.
- A refusal is a 403 whose body is a fixed sentence naming nothing; nothing is written or mailed; the audit line is `Refused username change by '<caller>': ... User <id> holds roles [...], groups [...], ACLs [...]` (or `password reset`). WP-0h's `Refused grant by` lines are unchanged.

The target is judged as it is before the request. A request that renames a user and in the same body removes the grants the caller lacks is refused; the caller can remove first, then rename.

### UserResourceManager: administrators through a group are hidden (decision 0010)

Round 1 did not adopt decision 0005 point 4. Its reasoning, that the takeover was closed at the two writes and hiding would only turn a 403 into a 404, was wrong (reviewer round 1, finding 3). At `0b79419` a non-superuser still reached an administrator through a group on other user routes, each with no audit line:
- `user_admin` alone: `DELETE /api2/user/<id>`, 204, the account deleted;
- `manager` alone: `DELETE /api2/user/<id>/force`, 204, the account and every dashboard and alert it wrote deleted;
- `manager` + `user_admin`: `PATCH` with status inactive, 200 (deactivated), and `PATCH` with groups `[]`, 200 (demoted: the target is no longer a superuser).

None raises the caller's own access, but together they let a lesser role remove every administrator of a deployment. Decision 0010 made the hiding a requirement of this WP.

`UserResourceManager._query` (`web/server/potion/managers.py`) leaves out users holding the admin role directly or through a group unless `SuperUserPermission().can()`. Superuser is the identity, as in WP-0h. So a token narrowed on an admin account no longer reaches direct administrators either: the old filter asked the account. A dashboard's `authorUsername` goes through the same rule (`managers.visible_username`, one query per request), so it no longer names an author the caller cannot list (row 6). One filter covers the list and every user item route (`DELETE`, `/force`, `PATCH`, `/roles`, `/reset_password`, `/password`, `/generate_api_token`, `/ownership`, `/can_export_data`, `/is_user_in_group`). Each answers 404 with nothing written and no audit line.

Residuals, each Low, owner WP-5d (decision 0010 point 4):
- lesser roles removing peers or higher users who are not administrators (delete, force-delete, deactivate, demote);
- force-delete destroying dashboards the caller cannot delete directly;
- removing a user from a group the caller is not in;
- self force-delete through `/force`;
- no audit line for successful destructive user operations.

Deactivated accounts keep full access today (sign-in, header login, existing tokens). That High is WP-0k's (decision 0010 point 3), not this WP's.

### How to run the tests

```bash
uv run --locked pytest tests/privilege_escalation -q
```

The harness is WP-0h's (see WP-0h.md). `test_rename_and_reset.py` stubs the mailer: the app's `email_renderer` and `notification_service`, plus `url_for` in `web/server/routes/views/admin.py` because the harness does not register the login pages. WP-0k replaces that `url_for` with a link built from `DEPLOYMENT_BASE_URL`; when it lands, the `mailer` fixture must stub the new helper instead.

## INV-3 difference table

Only principals that already pass a route's gate reach the new checks. The gates are unchanged:
- `edit_user` on site plus Potion's `edit_resource` on user for `PATCH /api2/user/<id>`;
- `reset_password` on user, sitewide or on that user, for `POST /api2/user/<id>/reset_password`.

| # | Principal | Request | Before | After |
|---|---|---|---|---|
| 1 | a non-superuser identity passing the `PATCH` gates: `manager` + `user_admin` among seeded roles, or an admin account's token narrowed to them | `PATCH /api2/user/<id>` with a `username` other than the stored one, on a user who is not an administrator and holds a role (direct or through a group) the caller's account does not hold, a group the caller is not in, or an ACL whose permissions the caller's account holds neither on that resource nor sitewide | 200; the username and the rest of the body are written | 403; nothing written (profile, roles, groups, ACLs); audit line |
| 2 | a non-superuser identity with `reset_password` on user: `user_admin`, `user_moderator`, either with `manager`, or a narrowed admin token | `POST /api2/user/<id>/reset_password` on such a user | 204; a reset token is stored and the link is mailed to the username | 403; no token stored, nothing mailed; audit line |
| 3 | any non-superuser identity (reading users is open to every signed-in user), a token narrowed on an admin account included | `GET /api2/user` and `GET /api2/user/<id>` on an administrator through a group; for a narrowed admin token, also on a direct administrator | listed; 200 | not listed; 404 |
| 4 | a non-superuser identity passing a user item route's permission: `user_admin` (`DELETE`, `/roles`, `/reset_password`), `manager` (`/force`), `manager` + `user_admin` (`PATCH`), `user_moderator` (`/reset_password`), or a narrowed admin token | every user item route on an administrator through a group (on a direct administrator too, for a narrowed admin token) | 200 or 204 and written: deleted, force-deleted with its dashboards and alerts, deactivated, demoted, roles cleared; a rename or reset was 200/204 before this WP and 403 under the round-1 guard | 404; nothing written; no audit line |
| 5 | non-superusers using pickers fed by `GET /api2/user`: dashboard sharing, alert recipients, group editors | choosing an administrator through a group | offered | not offered, as direct administrators already are not |
| 6 | any non-superuser identity that can view a dashboard | `GET /api2/dashboard/<id>` and `GET /api2/dashboard` on a dashboard written by an administrator, direct or through a group | `authorUsername` names the author (the `author` link already answered 404 for direct administrators, and since row 3 for group administrators too) | `authorUsername` is null, as the field's description says for an author the caller cannot see; `author` unchanged |

Rows 1 and 2 are decision 0005's row, spelled out per route; rows 3 to 6 are decision 0010's (row 6 from qa's request (g)). Administrators answer 404 (rows 3 and 4), so rows 1 and 2 apply to everyone else. In practice they refuse:
- users holding `_default_role` (query policies and data export) when the caller does not;
- dashboard authors, who get a `dashboard_admin` ACL on each dashboard they create, unless the caller holds dashboard permissions sitewide (for example the `dashboard_admin` role) or the same ACL;
- alert authors, who get an `alert_admin` ACL on each alert they create, for every non-superuser that does not hold the same ACL. The ACL yields `alert_definitions` needs as well as `alert` ones (`_maybe_build_alert_needs`). Roles yield `alert_definitions` needs only from ALERT entries in `role_permissions`, and no seeded role has one: the seeded alert roles grant through `alert_resource_role`, which yields `alert` needs only. So even the `alert_admin` role does not cover an alert author (`alert_acl_and_a_caller_with_the_alert_admin_role`);
- members of any group the caller is not in.

The callers are `manager` + `user_admin` (both routes), and `user_admin` or `user_moderator` alone (reset). A token narrowed on an admin account is refused like them. Before decision 0010 it also reached direct administrators, because the old `UserResourceManager` filter asked the account. It then got the row 1 and 2 refusals there; it now gets 404. Such callers must ask a superuser to rename or reset those users.

Refusing a bare reset is defence in depth: a reset mails the target's own address. The takeover needs a rename first (row 1), or a username that only looks like the target's and matches it at login (C1 in security's verdict, closed by WP-0k's exact matching).

Unchanged:
- Superusers (the identity), on both routes.
- Renames and resets of users whose roles, groups and ACLs are among the caller's, the caller itself included.
- `PATCH /api2/user/<id>` that keeps the username, on any user the caller reaches, whatever it holds. WP-0h's grant checks still apply.
- Callers without the gates: 401 from `AuthorizedOperation`, or 403 from Potion's check, with no audit line.
- Users holding the admin role directly: still 404 to every non-superuser full session.
- Superusers, direct or through a group: they still list and reach every user, administrators included.
- Users who hold more than the caller without being administrators: still listed and reachable; only a rename or reset is refused (rows 1 and 2).
- The anonymous `POST /api/forgot_password` (the user's own mailbox), `/api2/user/<id>/password` and `/generate_api_token` (both gated by `change_password` on user, which only superusers hold in the seed).
- The 400 for a legacy username that is not an e-mail address is now reached only after the guard: a refused target answers 403 first.

Seeded roles with no difference: `admin` (a superuser), and every other role except `user_admin` and `user_moderator`, because none passes either gate. `manager` holds `reset_password` and `edit_user` on site only, so on its own it passes neither. The admin UI's user editor sits behind `view_admin_page`; among the affected roles only `manager` holds it, so `manager` + `user_admin` sees the refusal in the UI as a failed save.

## Findings for the lead

- **Coupling with WP-0k.** WP-0k rebuilds the reset link from `DEPLOYMENT_BASE_URL` and changes username matching at login. This WP's mailer fixture patches `admin.url_for`; whichever lands second updates the fixture. WP-0j still allows renames to look-alike usernames of users the caller holds no less than; the login-side matching that makes look-alikes dangerous is WP-0k's.
- **Destructive user routes on administrators (reviewer round 1, finding 3).** Delete, force-delete, deactivate and demote reached administrators through a group; decision 0010 closed them here (rows 3 to 5). The Low residuals for WP-5d are listed under the `UserResourceManager` section. The deactivated-accounts High is WP-0k's.
- **A username over 50 characters is a 500 (pre-existing; route to WP-5d).** `USERNAME_SCHEMA` (`web/server/api/model_schemas.py`) has no `max_length`, so Potion accepts the body and the database rejects the write. Found by qa and security in round 1. It is the same on `488e482` and on this branch, and it is reached only after the guard passes. WP-5d's user schema should cap the length at the column's and answer 400.
- **`change_password` paths.** `/api2/user/<id>/password` and `/generate_api_token` hand over an account directly and are gated only by `change_password` on user. No seeded non-superuser role holds it, so nothing changes here. A custom role holding it would be a takeover path this rule does not cover; the WP-5d port should apply the same rule to every account-handover route.

## Human acceptance

Security asks the human to accept:
- INV-3 rows 1 and 2, including how broad they are in practice: a non-superuser user editor (`manager` + `user_admin`) or password resetter (`user_admin`, `user_moderator`) can no longer rename or reset dashboard authors, `_default_role` holders or members of other groups unless it holds the same access. Alert authors can be renamed or reset only by a superuser or a holder of the same alert ACL.
- **INV-3 rows 3 to 6 (decision 0010).** Dashboards written by administrators no longer name their author to non-superusers. No deployment needs a non-superuser to see, share with, or maintain administrator accounts. Offboarding an administrator (delete, deactivate, demote) becomes a superuser or shell task. If no superuser can sign in, the recovery path is `scripts/create_user.py --site_admin`, documented per deployment.
- **The Low residuals left to WP-5d:** lesser roles deleting, force-deleting, deactivating or demoting peers and higher users who are not administrators; force-delete destroying dashboards the caller cannot delete directly; removing a user from a group the caller is not in; self force-delete; no audit line for successful destructive user operations.

## Contract changes

None.

## Requests

- [x] qa: WP-2b has no live pin for the rename-and-reset takeover; its H5 entry covers only the user-list visibility, which does not change here. In this WP's stack, add and flip, in `tests/authz/http`: (a) `manager` + `user_admin` `PATCH /api2/user/<id>` changing the `username` of a user who is admin through a group, 200 with the username changed today, 403 with nothing changed after; (b) `user_admin` `POST /api2/user/<id>/reset_password` on the same user, 204 with a mail today (mailpit on the WP-2c stack), 403 and no mail after; (c) the unchanged controls, a rename and a reset of a user holding no more than the caller (200, 204). The `decisions.yaml` row `[reset_password, user, 43]` stays as it is: that check is still the gate, and the new refusal is a second check after it. `test_user_list_hides_admins_but_shows_everyone_else` is unchanged.
- [x] qa (decision 0010, supersedes parts of the request above): (a) and (b) now end in 404, not 403, with nothing written and no mail; add (d) a rename and a reset of a user who holds more without being an administrator (for example in a group carrying `exporter`): 200/204 today, 403 after; (e) flip the WP-2b list-visibility pin (`test_user_list_hides_admins_but_shows_everyone_else`): an administrator through a group is listed today and not after; (f) pin and flip the four destructive paths on an administrator through a group: `user_admin` `DELETE` 204, `manager` `DELETE /force` 204, `manager` + `user_admin` `PATCH` status inactive 200 and groups `[]` 200 today; 404 with nothing changed after; (g) check whether `authorUsername` on dashboards written by an administrator through a group goes null for non-superusers (the field's description says it is null when the author is not visible; whether it reads through `UserResourceManager` is the question), and whether the dashboard sharing, alert recipient and group editor pickers still load.
  - qa status 2026-10-06: built on `mig/WP-0j-rename-reset-guard-qa` (commit `ff23e0e` on `429bf96`, `tests/authz/http/test_account_handover.py`), not yet merged here, so both qa items stay open. (a) and (b) end in 404 as decision 0010 says; (c) and (d) are in; (f) covers `DELETE`, `/force`, deactivate, demote and `/roles`, plus rename, profile edit, reset and read. (e): WP-2b's `test_user_list_hides_admins_but_shows_everyone_else` checks only direct `admin` roles, so its outcome is the same before and after (it passes on `488e482` and `429bf96`); the flip is pinned here as `test_user_pickers_do_not_offer_an_admin_through_a_group`, and WP-2b's `test_lists.py` docstring needs its H5 note changed (request below). (g): `authorUsername` is not null; it still names a hidden administrator (request below). The pickers' API (`GET /api2/user?per_page=1000`, as `DirectoryService.getUsers` calls it, and the username lookup) answers 200 for `manager` + `user_admin`, `_default_role` and `dashboard_viewer` and leaves the administrator out; the rendered pickers were not opened in a browser.
- [x] lead: merge `mig/WP-0j-rename-reset-guard-qa` into this branch (one commit on `429bf96`, `tests/authz/http/test_account_handover.py` plus this file). The module skips (`pytest.importorskip`) until WP-2b's harness is on the same branch, so `ci/pytest_suites.sh` reports `tests/authz` as "no tests selected" here. Merged at round 2 unit 10.
- [x] security: rate (g). `GET /api2/dashboard/<id>` gives a non-superuser who can view the dashboard (`dashboard_viewer`) the `authorUsername` of an administrator through a group, and an `author` URI that answers 404. `AUTHOR_USERNAME_SCHEMA` says the field is null when the author is not visible, but `Dashboard.author_username` reads the relationship, not `UserResourceManager`. Pinned as it is by `test_dashboard_still_names_a_hidden_admin_author` (owner WP-5d unless security wants it in this WP). Superseded: the lead put (g) in this WP; fixed in round 2 unit 9 (INV-3 row 6).
- [ ] qa: flip `test_dashboard_still_names_a_hidden_admin_author` in `tests/authz/http/test_account_handover.py` (from `07c219b`): since unit 9 a non-superuser viewer gets `authorUsername` null for a dashboard written by an administrator through a group (the `author` URI still 404). Harness pin: `test_a_dashboard_names_its_author_only_to_callers_who_see_the_author`.
- [ ] qa (WP-2b, after WP-0j merges): change the H5 note in `tests/authz/http/test_lists.py` (admins through a group are no longer listed to non-superusers) and drop the `importorskip` bridge from `test_account_handover.py` once WP-2b and WP-0j share a branch. Neither can be done here without editing WP-2b's files.

## Log

- 2026-10-05 backend-0j unit 1: claimed; read decision 0005, phase 0j, `UserResource`, `send_reset_password` and WP-0h's `grants.py`. Commit `3afc320`.
- 2026-10-05 backend-0j units 2-3: 36 tests in `test_rename_and_reset.py` and the guard. Commit `a969ea8`. Check: on base `a615058` with the file copied in, `26 failed, 10 passed`; the 26 are every refusal case, failing on 200/204, and the 10 are the unchanged cases. On the branch the harness gives `117 passed`. Mutation pass: 10 of 10 mutants killed (below). black 22.6.0 clean; pylint 2.17.4 reports no errors.
- 2026-10-05 backend-0j unit 4: merged WP-0h round 3 (`b094556`, which merged `mig/integration` and moved the harness to `tests/privilege_escalation`). mypy flagged two untyped relationships and the import-time web mixin on `User`; added `# type: ignore[attr-defined]` with the reason, as WP-0h did. Check: `ci/lint_python.sh mig/WP-0h-privilege-escalations` clean on the three changed files; `uv run --locked mypy` no issues in 518 files; `uv run --locked pytest tests/privilege_escalation` 122 passed; `ci/pytest_suites.sh` all 9 suites passed (core 25, druid 1, druid_setup 79, golden 269, graphql 22, pipeline 129 + 1 skipped, privilege_escalation 122, toolchain 9, web 95).

- 2026-10-05 backend-0j unit 5: `UserResourceManager` change decided (not adopted, reasons above), INV-3 rows 1-2, human acceptance, Request to qa. Check: this file.
- 2026-10-05 backend-0j unit 6: `pstack:interrogate` could not start: the session was at its limit of 20 concurrent subagents, and the skill says not to retry. I did the adversarial pass myself instead (below). Status `review`.
- 2026-10-05 backend-0j unit 7 (lead request): merged WP-0h `488e482` (its merge of integration `e86d91a` and the restored 3.8 `with` statement; one conflict, the backend memory index, kept both entries), then `mig/integration` `61db9f8` (py38 ruff target, 3.8 syntax guard). Merge commits `b0625fd`, `03c79c4`. Check on the merged head:
  - `uv run --no-project -p cpython-3.8.20 python ci/check_py38_syntax.py config data db log models graphql util web scripts tests/web tests/privilege_escalation`: 849 files checked, 0 problems;
  - `ci/lint_python.sh mig/WP-0h-privilege-escalations`: ruff clean, 5 changed files formatted; `ci/lint_python.sh mig/integration`: ruff clean, 12 changed files (WP-0h's and this WP's) formatted;
  - `uv run --locked mypy`: no issues in 518 source files;
  - `ci/pytest_suites.sh`: all 9 suites passed (core 25, druid 1, druid_setup 79, golden 269, graphql 22, pipeline 129 + 1 skipped, privilege_escalation 122, toolchain 12, web 95);
  - CPython 3.8.20 (`/tmp/wp2g-be3-py38`, the web image's version): `python -m pytest tests/privilege_escalation` 122 passed; `py_compile` of the three changed Python files passes.
- 2026-10-05 backend-0j round 2 unit 1 (reviewer finding 1): two higher targets pin the `all` in `_holds_acl` and the resource id: the caller holds `dashboard_viewer` on the target's `dashboard_admin` dashboard, and `dashboard_admin` on another dashboard. Check: `test_rename_and_reset.py` 44 passed; mutants `all` to `any` and resource id ignored pass the round-1 file (36 passed each) and fail 4 tests each on the new one (`/tmp/wp0j-r2/mutate.py`); ruff clean.
- 2026-10-05 backend-0j round 2 unit 2 (reviewer finding 2, QA low): `test_a_rename_is_judged_on_the_user_before_the_request`, for a target in a group carrying `admin` and one carrying `exporter`, renames while dropping that group and changing `lastName`: 403, username, last name, roles, groups and ACLs unchanged, one refusal line. Every higher-target rename case now also changes `lastName` and asserts the same five unchanged. Check: 46 passed; the mutant that judges the body's groups passes the round-1 file (36 passed) and fails both new cases; ruff clean.
- 2026-10-05 backend-0j round 2 unit 3 (decision 0010, replacing reviewer finding 3's correction): `UserResourceManager` hides administrators, direct or through a group, from every non-superuser identity (`SuperUserPermission().can()`). Tests: the five item routes (delete, force-delete, deactivate, demote, clear roles) 404 with nothing changed and no audit line; hidden from `GET /api2/user` and `GET /api2/user/<id>` for no roles, `manager` + `user_admin` and `user_moderator`; superusers direct and through a group still list, get and deactivate; users holding more but not admin still listed; narrowed admin tokens see neither direct nor group administrators. Admin-through-group rename and reset cases moved from 403 to 404; the guard cases keep their non-admin targets; WP-0h's `test_user_editor_removes_grants_it_does_not_hold` moved its target's group from `admin` to `exporter`. Check: at `b090396` with the new tests, 12 failed (200/204 instead of 404, listed) and 58 passed; after, harness 156 passed; mutants (group clause removed, direct clause removed, decided by the account) fail 11, 4 and 3 tests; ruff clean.
- 2026-10-05 backend-0j round 2 unit 4 (reviewer finding 4): three tests pin the order and the exact comparison at `user_api_models.py:152-155`, each on a target in a group carrying `exporter`: `manager` alone renaming gets 403 from Potion's check with nothing written and no refusal line; a rename that also adds `group_admin` (not held) logs exactly one line, the username-change refusal; a case-only rename is 403 with one refusal. Check: 73 passed; mutants rename check before `can_update_item`, rename check after the grant checks, and a case-insensitive comparison each pass the file at `b090396` (46 passed) and fail one new test each; ruff clean.
- 2026-10-06 backend-0j round 2 unit 5 (reviewer finding 5): breadth note corrected. It now covers alert authors, with a test target where the caller holds the `alert_admin` role and the target an `alert_admin` ACL: refused on rename and on reset by all three callers. It names `user_moderator`, and says that narrowed admin tokens reached direct administrators before decision 0010 and get 404 now. It also says a bare reset mails the target's own address (C1, WP-0k). The interrogate note's alert claim is corrected too. `_resent_body` now sends each ACL's own resource type. Check: 78 passed; ruff clean.
- 2026-10-06 backend-0j round 2 unit 6 (reviewer finding 6): `grants.held_role_ids()` and `grants.member_group_ids()` hold the two rules (admin role, and groups carrying it, never held by a non-superuser identity). `held_roles_from_uris`, `member_groups_from_uris`, the guard, `RoleResourceManager` and `GroupResourceManager` all call them. The guard's group set now also leaves out admin-carrying groups; only narrowed tokens see a difference, and only in the audit line, because those targets already fail on the admin role. `_holds_acl` builds needs from `current_user`, which drops the third `type: ignore`. Check: harness 164 passed; `uv run --locked mypy` no issues in 518 files; `web.server.potion.managers` imports on its own (no cycle); ruff clean.
- 2026-10-06 backend-0j round 2 unit 7 (reviewer finding 7): the over-50-character 500 recorded under Findings, routed to WP-5d. A QA-4 evidence line maps each phase-0j verification bullet to its evidence; the WP-2b pin flip and the acceptance of rows 3 to 5 are the open items. The mutation table was rerun in full at `773fbcb` (21 mutants, every one killed by this file or by the whole harness). Check: this file.
- 2026-10-06 backend-0j round 2 unit 8 (lead, from WP-0k's QA gate): the `refusals` fixture records on its own handler on `ZenysisLogger`, as WP-0h's does, so integration's propagating logger (WP-2g `log/config.py`) does not count each audit line twice. Check: with propagation forced on per test (a pytest plugin in `/tmp/wp0j-r2/plug`), 44 failed before and 78 passed after; 78 passed with it off; ruff clean.
- 2026-10-06 backend-0j round 2 unit 9 (qa request (g), via the lead): a dashboard's `authorUsername` goes through decision 0010's rule. `managers.visible_username` returns null when the caller is not a superuser and the author is an administrator (direct or through a group), with one query per request; `UserResourceManager` and it share `_administrators()`. INV-3 row 6. Touching `dashboard_api_models.py` pulled in the changed-file lint: an unused `SchedulerEntry` import was removed (`web/server/app_base.py` imports the module) and two strings were reformatted. Check: `test_a_dashboard_names_its_author_only_to_callers_who_see_the_author` (item and list, for a viewer and a superuser) failed 2 of 3 before (the author named) and passes after; harness 167 passed; `tests/web` 95 passed; mypy clean; ruff clean.

- 2026-10-06 qa (supporting role, `mig/WP-0j-rename-reset-guard-qa`): live pins for the requests above in `tests/authz/http/test_account_handover.py`, on WP-2b's live harness (`39b3a64`) and the WP-2c stack (`2c8928a`, reusing image `harmony-contract-web-server:f46617f35db7`, whose hash both trees match). 46 tests. Non-administrators holding more than the caller (`_default_role` holder, foreign group member, member of a group carrying an exporting role, dashboard author through a real `POST /api2/dashboard`): rename and reset by `manager` + `user_admin`, resets by `user_admin` and `user_moderator`, 403 with nothing written, no token, no mail and one audit line naming the caller. Administrators through a group: 11 item requests 404 with nothing written, no mail and no audit line; left out of the pickers' list and lookup for three roles; H5 end to end sends 0 mails to the attacker's address. Controls: equal roles, no grants, shared group, callers holding `_default_role` or the `dashboard_admin` role, profile edit, superuser list and rename and reset, self reset, `manager` alone and `user_admin` alone 401, direct admin 404. Pinned as they are, owner WP-5d: rename over 50 characters 500 with nothing written; `authorUsername` naming a hidden admin author. Checks, one fresh stack at a time, volumes removed after each:
  - `429bf96` tree: 46 passed; the whole live layer 616 passed and 13 failed. The 13 are WP-2b's 10 WP-0h escalation pins, still waiting for qa's flip unit, and 3 `test_api_tokens.py` pins of WP-2c's F12 fix, which is not on this tree. The same 13 fail on `488e482`, so no WP-2b pin changes outcome with WP-0j.
  - `488e482` tree: 26 failed and 20 passed. Every failure is the pre-WP-0j behaviour: 200/204 instead of 403 (10), 200/204 instead of 404 (11 plus the hidden author's URI), the administrator listed (3), and one mail to the attacker's address (H5). The 20 controls pass on both trees.
  - Before the owner's `429bf96` landed, the same file on the `b090396` code tree had the 8 admin-through-group pins as strict `xfail`: they failed on 403 (rename, reset) and 200 (profile edit, read), and the list showed the administrator. The marker was dropped once `429bf96` was on the branch.
  - WP-2b pure layer: 4675 passed on `488e482`, `dc8989a` and `429bf96`. Lint: `ci/lint_python.sh mig/WP-0j-rename-reset-guard` clean. 3.8: `check_py38_syntax.py tests/authz` 0 problems, `py_compile` under CPython 3.8.20 passes. On the branch alone, `pytest tests/authz` gives 1 skipped (exit 5, which `ci/pytest_suites.sh` reports as no tests selected). Leftovers after each run: 0 test users, groups, dashboards and handover roles.
  - Mail is counted per address before and after each request, because creating a dashboard also mails its author. `test_rename_and_reset.py:247-263` needed no request: the owner's round 2 unit 2 (`b090396`) changes `lastName` and asserts the five holdings unchanged. Evidence: `/tmp/wp0jqa/final-429bf96/`, `/tmp/wp0jqa/final-488e482/` (`handover.txt`, `live-all.txt`, `refusals.txt`, `web.log`), `/tmp/wp0jqa/pure-*.txt`, `/tmp/wp0jqa/run-xfail-0j/`.
- 2026-10-06 backend-0j round 2 unit 10: merged qa's pin branch `07c219b` (`tests/authz/http/test_account_handover.py`). One conflict, in this file's Requests; kept both sides. The qa merge and the security (g) items are closed: (g) was fixed here in unit 9. The authorUsername flip goes back to qa.
- 2026-10-06 backend-0j round 2 unit 11: merged `mig/integration` `bc5cb2d` (WP-0i, 2b, 2c, 2g, 4a, 8a, 0h) as the lead asked. Merge commit `ff5325c`. The one conflict was the backend memory index; both sides kept. `user_api_models.py` merged cleanly, with `issue_api_token` and `replace_user_acls` kept. The `importorskip` bridge in `tests/authz/http/test_account_handover.py` is left to qa: the file is qa's, and I reverted my edit. The qa-0j-pins instance now claims that file. Checks on `ff5325c`:
  - `ci/pytest_suites.sh` exit 0: alerts 9, authz 4681 + 629 skipped (live layer, no stack), contract 60, core 185, db 26, druid 17 + 11 skipped, druid_setup 83, golden 272, graphql 22, pipeline 129 + 1 skipped, privilege_escalation 167 (with the propagating logger), toolchain 12, web 283 + 1 xfailed;
  - `ci/lint_python.sh mig/integration`: ruff clean, 7 changed files formatted; `uv run --locked mypy`: no issues in 519 files;
  - `check_py38_syntax.py` under CPython 3.8.20 (with `tests/authz`): 888 files, 0 problems;
  - CPython 3.8.20 (`/tmp/wp2g-be3-py38`, plus integration's new `pydantic` 2.10.6, `pydantic-settings` 2.8.1 and `typing_extensions` 4.12.2 installed with `pip --target /tmp/wp0j-r2/py38extra` on `PYTHONPATH`): `tests/privilege_escalation` 167 passed;
  - `task_gate.py WP-0j`: only status `review` and the reviewer's changes-requested verdict remain. WP-0h's files no longer show, because 0h came in through integration.

## Interrogate (unit 6)

The three-model panel did not run (concurrent subagent limit). The reviewer prompt is saved at `/tmp/wp0j-interrogate-prompt.md` so the lead can run it when slots are free; the security review is the independent adversarial pass meanwhile. My own pass, against the prompt's hunt list:
- **Other routes that change a username or hand over an account.** Potion keys routes by relation, so `update_user` (`rel='update'`) replaces the default `PATCH`; no other route writes `username`. `POST /api2/user` creates and cannot take an existing username. Invites mail the invitee's own address. `/password` and `/generate_api_token` need `change_password` (superuser only in the seed; see Findings for the lead). No gap.
- **Username comparison.** Any difference, case or whitespace included, counts as a rename and is checked. That is conservative, so there is no bypass.
- **Needs a target can hold.** Group ACLs come with membership, and sitewide ACLs are the same for every registered user. Role resource roles, policies and export come with the role. Round 1 said `alert_definitions` needs from an alert ACL were covered by a sitewide need from an alert role. They are not: seeded alert roles yield `alert` needs only (reviewer round 1, finding 5). The rule errs towards refusing there (see the breadth list). No gap.
- **Source of truth.** The superuser decision uses the identity; holdings use the account, minus admin. This matches WP-0h and is pinned by the narrowed-token test.
- **Ordering.** Both checks run before any write or mail. The rename check runs before WP-0h's grant checks, so a refused rename never logs a grant refusal too.
- **403 body.** A fixed sentence. It tells the caller the target holds more than it does, but the user list already shows the target's roles.
- **Test gaps.** Round 1 said every clause had a mutant that fails. It did not: in `_holds_acl` nothing pinned that every need of an ACL must be held (`all` to `any`) or that the resource id counts, and both mutants passed the 36 tests (reviewer round 1, finding 1). Round 2 adds the two targets that kill them and the mutants for ordering and for judging the stored user (below).

## Evidence

- **QA-4 (phase 0j verification, one line per bullet).**
  - *Failing test first, then 403 with nothing written and no mail:* round 1's 26 refusal tests fail on `488e482` on status codes only (QA-1 below). Under decision 0010 the admin-through-group case answers 404, not 403 (`test_user_editor_cannot_take_over_an_admin_through_a_group`, and the five destructive routes in `test_user_routes_cannot_reach_an_admin_through_a_group`). Every other higher target answers 403 with username, last name, roles, groups, ACLs and status unchanged and the stub mailer empty (`test_user_editor_cannot_take_over_a_user_holding_more`, `..._cannot_rename_a_user_holding_more`, `..._cannot_reset_the_password_of_a_user_holding_more`).
  - *Equal-or-lesser targets unchanged:* `test_user_editor_renames_and_resets_a_user_holding_no_more` (5 targets), `test_user_editor_resets_its_own_password`, `test_users_holding_more_but_not_admin_stay_listed_and_reachable`, and the superuser tests, all passing on base and branch.
  - *WP-2b pins flip in the same stack; security and the human accept the INV-3 rows:* open. qa's side branch `mig/WP-0j-rename-reset-guard-qa` adds and flips the pins (Requests), and is merged here when the lead reports its head. Security approved rows 1 and 2 in round 1; rows 3 to 5 (decision 0010) and the human item are pending.
  - *Phase 0 exit check (every page renders):* qa's round 1 browser check at three widths. The admin user list under decision 0010 is in qa's request (g).
- **QA-1.** The refusal tests fail on the base for H5's reason: `assert 204 == 403` (18 reset cases), `assert 200 == 403` (6 rename cases), and `(200, 204) == (403, 403)` for the end-to-end takeover and the narrowed-token case.
- **Unchanged behaviour** passes on base and branch: renames and resets of users holding no grants, the same roles, fewer roles one of them through a shared group, the same ACL, and an ACL covered by a sitewide role; a reset of one's own password; a profile edit of an admin through a group that keeps the username; a superuser renaming and resetting an admin through a group; `manager` alone resetting (401, no audit line); a full admin session through the token path.
- **Audit line.** `test_user_editor_cannot_take_over_an_admin_through_a_group` checks two refusal lines naming the caller; each refusal case checks exactly one.
- **Mutation pass, round 2** (`/tmp/wp0j-r2/mutate.py`, at `773fbcb`). Each mutant is applied to a copy of the tree and run against `test_rename_and_reset.py` (78 tests) unless the row says otherwise. Round 1's table claimed every clause was pinned; the first two ACL rows and the ordering rows show it was not.

  | Mutant | Result |
  |---|---|
  | rename check removed | 20 failed |
  | reset check removed | 32 failed |
  | rename check on every edit, username kept or not | 1 failed (`still_edits_the_profile...`) |
  | case-insensitive username comparison | 1 failed (`a_rename_that_changes_only_case_is_a_rename`); passed the file at `b090396` |
  | rename check before Potion's `can_update_item` | 1 failed (`a_rename_without_edit_resource...`); passed at `b090396` |
  | rename check after the grant checks | 1 failed (`a_rename_is_judged_before_what_the_body_grants`); passed at `b090396` |
  | rename judged on the written user (guard after the writes) | 20 failed |
  | rename judged on the request body (the body's groups set, then the guard) | 3 failed (`a_rename_is_judged_on_the_user_before_the_request[exporter]`, `[group_admin]`, `..._before_what_the_body_grants`); passed the round-1 file |
  | superuser early return removed | 2 failed |
  | roles ignored | 15 failed |
  | groups ignored | 3 failed (`group_not_joined`) |
  | ACLs ignored | 20 failed |
  | no sitewide cover for ACLs | 1 failed (`acl_covered_by_a_held_role`) |
  | no exact cover for ACLs | 1 failed (`acl_the_caller_holds_too`) |
  | any need of an ACL covers it (`all` to `any`) | 10 failed (`dashboard_acl_the_caller_only_views`, `alert_acl_and_a_caller_with_the_alert_admin_role`); passed the round-1 file |
  | resource id ignored (an ACL on one dashboard covers another) | 5 failed (`dashboard_acl_on_another_dashboard`); passed the round-1 file |
  | administrators through a group not hidden (`UserResourceManager`) | 11 failed |
  | direct administrators not hidden | 4 failed |
  | hiding decided by the account, not the identity | 3 failed (the narrowed-token cases) |
  | `held_role_ids()` counts the admin role | this file: 78 passed, because no reachable target holds admin since decision 0010. Whole harness: 4 failed (WP-0h's narrowed-token tests) |
  | `member_group_ids()` counts groups carrying admin | this file: 78 passed (same reason). Whole harness: 2 failed (WP-0h's narrowed-token tests) |

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-05 qa-0j at 19b9f62 (code 63bbd89): 36 tests pass, 26 fail on 488e482 on status codes only; harness 122 pass incl. on CPython 3.8.20; trial merge with 3e538e2 clean and every gate green (9 suites, lint, 3.8 guard, mypy, tools313); WP-2b pure layer identical; two fresh stacks: refused cases 403/403 with nothing written, no token, 0 mails, one audit line each, no PII in audit lines; breadth cases refused; equal-or-lesser targets, profile edits, superusers, self reset unchanged; browser check at three widths. Low, pre-existing: rename over 50 characters is 500 on base and branch (USERNAME_SCHEMA lacks max_length; backend WP-5d or follow-up); test_rename_and_reset.py:247-263 also change lastName and assert roles and ACLs unchanged. Info: WP-2b pins to add and flip (manager+user_admin rename and reset on admin-through-group, H5 mail 1 to 0, breadth pins, unchanged controls, the 500 pin) is QA's next unit. |
| reviewer | changes-requested | 2026-10-05 Round 1 at 19b9f62 (code 63bbd89): guard correct and no route around it; 26 fail on base; mailer stub on the real path; trial merge with 3e538e2 green on every gate incl. 3.8; interrogate panel (opus, fable, sonnet) agreed on findings 1, 2, 6. Medium: (1) no test pins all in _holds_acl (grants.py:321; all to any passes 36 tests; resource id ignored would too): add caller viewer on D vs target admin on D, and admin on D1 vs D2, fix the mutation table and the line 145 claim. (2) every rename test resends the target unchanged so judged-before-the-request and nothing-written are unpinned: rename an admin-through-group target while dropping the admin group and changing lastName, expect 403 and all unchanged. (3) WP-0j.md:58-63,111 UserResourceManager reasoning is wrong: at head user_admin alone DELETEs an admin-through-group (204), manager alone force-deletes (204), manager+user_admin deactivates and demotes (200); correct the reasoning, list these in the residual and the human item, record for security to rate (WP-5d or adopt hiding). Low: (4) user_api_models.py:152-155 pin ordering and exact comparison with three tests (manager alone 403 with no refusal line; rename plus unheld role logs one refusal; case-only rename 403). (5) WP-0j.md:96,110,141 breadth note: narrowed admin tokens reach direct admins; seeded alert roles yield no alert_definitions need so alert authors are refused to every non-superuser; name user_moderator; say a bare reset mails the target's own address. (6) grants.py:280-285 duplicate held-role and member-group rules, extract helpers; drop the third type ignore by building needs from current_user. (7) record the over-50 500 under Findings (WP-5d) and add a QA-4 evidence line mapping phase-0j bullets. |
| security | approved | 2026-10-05 sec-0j at 63bbd89: harness 122 passed on head and the new file 26 failed 10 passed on base 488e482; two disposable stacks (head and base, synthetic accounts): H5 rename then reset 200/204 with mail on base and 403/403 with nothing written and no mail on head; targets holding _default_role, a dashboard_admin ACL or a foreign group membership, rename plus admin-group removal in one request, case-only renames and user_moderator resets all refused; direct admins still 404; lesser or equal targets, self-reset, profile edits and superusers unchanged; manager alone 401 with no audit line; narrowed tokens refused in-process; 403 bodies a fixed sentence; audit lines carry no password, token or new username; semgrep 0 on the two production files; ownership clean; not adopting the UserResourceManager change agreed. Pre-existing, not blocking: C1 High owner WP-0k, self or lesser-account renames to a username that pattern-matches an admin's stay accepted until exact matching lands (merge 0j with 0k; 0k tests must cover PATCH renames and Flask-User's /user/change-username page, enabled for every user); C2 Low WP-0k refuse usernames equal ignoring case on rename; C3 Low /password and /generate_api_token gated only by change_password (defence in depth now optional, WP-5d required; human to check for custom roles holding it); C4 Low WP-5d token rows via PATCH; C5 Low SEC-6 reset links not single-use (rotate the reset secret on deploy); C6 info audit lines omit the requested username. For qa: a rename to more than 50 characters returns 500 after the guard. Human must accept INV-3 rows 1-2 and the breadth (dashboard authors, _default_role holders, group members need a superuser). |
