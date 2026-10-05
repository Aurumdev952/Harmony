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
      - "tests/privilege_escalation/test_rename_and_reset.py"
      - "docs/modernisation/work/WP-0j.md"
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

### How H5 works

`PATCH /api2/user/<id>` is gated by `edit_user` on site plus Potion's `edit_resource` on user; the seeded holders of both are `manager` + `user_admin`. WP-0h checks what the body grants, and resending the target's current groups is allowed, so a rename keeps a group carrying the admin role. `POST /api2/user/<id>/reset_password` is gated by `reset_password` on user (`user_admin`, `user_moderator`); `send_reset_password(user.username)` stores a reset token and mails the link to the username. Rename to an address the caller reads, then reset: the caller sets the admin's password. `UserResourceManager` hides only users holding the admin role directly, so an admin through a group is reachable.

### The rule

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

### UserResourceManager (optional change): not adopted

Decision 0005 point 4 lets the builder hide users who are admins through a group from non-superusers. Not adopted in WP-0j, for security to confirm:

- The takeover is closed at the two writes, for every target holding more than the caller, not only admins. Hiding would turn the admin case's 403 into a 404 and close nothing more.
- Hiding changes reads for every non-superuser. `GET /api2/user` feeds the user pickers (sharing a dashboard, alert recipients, group editors), so admins through a group would disappear from them for every non-admin, an INV-3 change outside decision 0005's rows.
- It would also stop a non-superuser user editor from editing or demoting such a user (404 on every item route), a second behaviour change.
- WP-2b's triage already assigns H5's list visibility (admins through a group appear in non-admins' user lists, Low, part of I1) to WP-5d, where the user list is rebuilt on FastAPI with explicit `can()` checks and the direct-admin rule can be decided with it, from the identity rather than the account.

Residual: a non-superuser who lists users still sees admins through a group (Low, information disclosure, unchanged). It can no longer take them over.

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
| 1 | a non-superuser identity passing the `PATCH` gates: `manager` + `user_admin` among seeded roles, or an admin account's token narrowed to them | `PATCH /api2/user/<id>` with a `username` other than the stored one, on a user holding a role (direct or through a group, admin included) the caller's account does not hold, a group the caller is not in, or an ACL whose permissions the caller's account holds neither on that resource nor sitewide | 200; the username and the rest of the body are written | 403; nothing written (profile, roles, groups, ACLs); audit line |
| 2 | a non-superuser identity with `reset_password` on user: `user_admin`, `user_moderator`, either with `manager`, or a narrowed admin token | `POST /api2/user/<id>/reset_password` on such a user | 204; a reset token is stored and the link is mailed to the username | 403; no token stored, nothing mailed; audit line |

Rows 1 and 2 are decision 0005's row, spelled out per route. In practice the refused targets include more than administrators:
- users holding `_default_role` (query policies and data export) when the caller does not;
- dashboard authors, who get a `dashboard_admin` ACL on each dashboard they create, unless the caller holds dashboard permissions sitewide (for example the `dashboard_admin` role) or the same ACL;
- members of any group the caller is not in.

A non-superuser user editor must ask a superuser to rename or reset those users.

Unchanged:
- Superusers (the identity), on both routes.
- Renames and resets of users whose roles, groups and ACLs are among the caller's, the caller itself included.
- `PATCH /api2/user/<id>` that keeps the username, on any user the caller reaches, whatever it holds. WP-0h's grant checks still apply.
- Callers without the gates: 401 from `AuthorizedOperation`, or 403 from Potion's check, with no audit line.
- Users holding the admin role directly: still 404 to non-superusers (`UserResourceManager`). Admins through a group stay listed and reachable (see the not-adopted change above).
- The anonymous `POST /api/forgot_password` (the user's own mailbox), `/api2/user/<id>/password` and `/generate_api_token` (both gated by `change_password` on user, which only superusers hold in the seed).
- The 400 for a legacy username that is not an e-mail address is now reached only after the guard: a refused target answers 403 first.

Seeded roles with no difference: `admin` (a superuser), and every other role except `user_admin` and `user_moderator`, because none passes either gate. `manager` holds `reset_password` and `edit_user` on site only, so on its own it passes neither. The admin UI's user editor sits behind `view_admin_page`; among the affected roles only `manager` holds it, so `manager` + `user_admin` sees the refusal in the UI as a failed save.

## Findings for the lead

- **Coupling with WP-0k.** WP-0k rebuilds the reset link from `DEPLOYMENT_BASE_URL` and changes username matching at login. This WP's mailer fixture patches `admin.url_for`; whichever lands second updates the fixture. WP-0j still allows renames to look-alike usernames of users the caller holds no less than; the login-side matching that makes look-alikes dangerous is WP-0k's.
- **`change_password` paths.** `/api2/user/<id>/password` and `/generate_api_token` hand over an account directly and are gated only by `change_password` on user. No seeded non-superuser role holds it, so nothing changes here. A custom role holding it would be a takeover path this rule does not cover; the WP-5d port should apply the same rule to every account-handover route.

## Human acceptance

Security asks the human to accept:
- INV-3 rows 1 and 2, including how broad they are in practice: a non-superuser user editor can no longer rename or reset dashboard authors, `_default_role` holders or members of other groups unless it holds the same access.
- **The not-adopted `UserResourceManager` change.** Admins through a group stay visible in non-admins' user lists until WP-5d (Low).

## Contract changes

None.

## Requests

- [ ] qa: WP-2b has no live pin for the rename-and-reset takeover; its H5 entry covers only the user-list visibility, which does not change here. In this WP's stack, add and flip, in `tests/authz/http`: (a) `manager` + `user_admin` `PATCH /api2/user/<id>` changing the `username` of a user who is admin through a group, 200 with the username changed today, 403 with nothing changed after; (b) `user_admin` `POST /api2/user/<id>/reset_password` on the same user, 204 with a mail today (mailpit on the WP-2c stack), 403 and no mail after; (c) the unchanged controls, a rename and a reset of a user holding no more than the caller (200, 204). The `decisions.yaml` row `[reset_password, user, 43]` stays as it is: that check is still the gate, and the new refusal is a second check after it. `test_user_list_hides_admins_but_shows_everyone_else` is unchanged.

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

## Interrogate (unit 6)

The three-model panel did not run (concurrent subagent limit). The reviewer prompt is saved at `/tmp/wp0j-interrogate-prompt.md` so the lead can run it when slots are free; the security review is the independent adversarial pass meanwhile. My own pass, against the prompt's hunt list:
- **Other routes that change a username or hand over an account.** Potion keys routes by relation, so `update_user` (`rel='update'`) replaces the default `PATCH`; no other route writes `username`. `POST /api2/user` creates and cannot take an existing username. Invites mail the invitee's own address. `/password` and `/generate_api_token` need `change_password` (superuser only in the seed; see Findings for the lead). No gap.
- **Username comparison.** Any difference, case or whitespace included, counts as a rename and is checked. That is conservative, so there is no bypass.
- **Needs a target can hold.** Group ACLs come with membership, and sitewide ACLs are the same for every registered user. Role resource roles, policies and export come with the role. `alert_definitions` needs from an alert ACL are covered by the sitewide `alert_definitions` need an alert role yields. No gap.
- **Source of truth.** The superuser decision uses the identity; holdings use the account, minus admin. This matches WP-0h and is pinned by the narrowed-token test.
- **Ordering.** Both checks run before any write or mail. The rename check runs before WP-0h's grant checks, so a refused rename never logs a grant refusal too.
- **403 body.** A fixed sentence. It tells the caller the target holds more than it does, but the user list already shows the target's roles.
- **Test gaps.** Every clause has a mutant that fails (below).

## Evidence

- **QA-1.** The refusal tests fail on the base for H5's reason: `assert 204 == 403` (18 reset cases), `assert 200 == 403` (6 rename cases), and `(200, 204) == (403, 403)` for the end-to-end takeover and the narrowed-token case.
- **Unchanged behaviour** passes on base and branch: renames and resets of users holding no grants, the same roles, fewer roles one of them through a shared group, the same ACL, and an ACL covered by a sitewide role; a reset of one's own password; a profile edit of an admin through a group that keeps the username; a superuser renaming and resetting an admin through a group; `manager` alone resetting (401, no audit line); a full admin session through the token path.
- **Audit line.** `test_user_editor_cannot_take_over_an_admin_through_a_group` checks two refusal lines naming the caller; each refusal case checks exactly one.
- **Mutation pass** (`/tmp/wp0j-mutate.py`, each mutant run against the new file):

  | Mutant | Result |
  |---|---|
  | rename check removed | 8 failed |
  | reset check removed | 20 failed |
  | rename check on every edit, username kept or not | 1 failed (`still_edits_the_profile...`) |
  | superuser early return removed | 2 failed |
  | admin role counted as held | 1 failed (`narrowed`) |
  | roles ignored | 13 failed |
  | groups ignored | 2 failed (`group_not_joined`) |
  | ACLs ignored | 4 failed (`dashboard_acl`) |
  | no sitewide cover for ACLs | 1 failed (`acl_covered_by_a_held_role`) |
  | no exact cover for ACLs | 1 failed (`acl_the_caller_holds_too`) |

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-05 qa-0j at 19b9f62 (code 63bbd89): 36 tests pass, 26 fail on 488e482 on status codes only; harness 122 pass incl. on CPython 3.8.20; trial merge with 3e538e2 clean and every gate green (9 suites, lint, 3.8 guard, mypy, tools313); WP-2b pure layer identical; two fresh stacks: refused cases 403/403 with nothing written, no token, 0 mails, one audit line each, no PII in audit lines; breadth cases refused; equal-or-lesser targets, profile edits, superusers, self reset unchanged; browser check at three widths. Low, pre-existing: rename over 50 characters is 500 on base and branch (USERNAME_SCHEMA lacks max_length; backend WP-5d or follow-up); test_rename_and_reset.py:247-263 also change lastName and assert roles and ACLs unchanged. Info: WP-2b pins to add and flip (manager+user_admin rename and reset on admin-through-group, H5 mail 1 to 0, breadth pins, unchanged controls, the 500 pin) is QA's next unit. |
| reviewer | pending | |
| security | approved | 2026-10-05 sec-0j at 63bbd89: harness 122 passed on head and the new file 26 failed 10 passed on base 488e482; two disposable stacks (head and base, synthetic accounts): H5 rename then reset 200/204 with mail on base and 403/403 with nothing written and no mail on head; targets holding _default_role, a dashboard_admin ACL or a foreign group membership, rename plus admin-group removal in one request, case-only renames and user_moderator resets all refused; direct admins still 404; lesser or equal targets, self-reset, profile edits and superusers unchanged; manager alone 401 with no audit line; narrowed tokens refused in-process; 403 bodies a fixed sentence; audit lines carry no password, token or new username; semgrep 0 on the two production files; ownership clean; not adopting the UserResourceManager change agreed. Pre-existing, not blocking: C1 High owner WP-0k, self or lesser-account renames to a username that pattern-matches an admin's stay accepted until exact matching lands (merge 0j with 0k; 0k tests must cover PATCH renames and Flask-User's /user/change-username page, enabled for every user); C2 Low WP-0k refuse usernames equal ignoring case on rename; C3 Low /password and /generate_api_token gated only by change_password (defence in depth now optional, WP-5d required; human to check for custom roles holding it); C4 Low WP-5d token rows via PATCH; C5 Low SEC-6 reset links not single-use (rotate the reset secret on deploy); C6 info audit lines omit the requested username. For qa: a rename to more than 50 characters returns 500 after the guard. Human must accept INV-3 rows 1-2 and the breadth (dashboard authors, _default_role holders, group members need a superuser). |
