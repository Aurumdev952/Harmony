# 0010. WP-0j hides administrators-through-a-group; WP-0k refuses deactivated accounts

Status: applied by the lead on 2026-10-05, pending human ratification (SPEC section 10).

## Context

The WP-0j code review and a follow-up security rating (both at `0b79419`, on a disposable stack with synthetic accounts) established four pre-existing paths, unchanged since `main`, by which a non-superuser reaches an administrator whose admin role comes through a group (direct administrators are hidden by `UserResourceManager` and get 404):

| Path | Caller | Result today | Rating |
|---|---|---|---|
| `DELETE /api2/user/<id>` | `user_admin` alone | 204, account and its roles, groups, ACLs, tokens gone | Medium |
| `DELETE /api2/user/<id>/force` | `manager` alone | 204, account plus every dashboard and alert it wrote | Medium |
| `PATCH` status inactive | `manager` + `user_admin` | 200 | Low today (see below) |
| `PATCH` groups `[]` | `manager` + `user_admin` | 200, target loses superuser | Medium |

None raises the caller's own access (WP-0h stops self-grants), so none is High; but together they let a lesser role remove every administrator of a deployment, with no audit line, recoverable only from shell or backup. Decision 0005 point 4 already named the fix as optional.

The same rating found a High outside WP-0j: **deactivated accounts keep full access.** A user with status inactive can still sign in through `POST /api2/authentication/login` (new 365-day token), through the `X-Username`/`X-Password` headers, and with any token issued before deactivation; nothing under `web/` checks `is_active`. Code identical on `main`.

## Decision

1. **WP-0j adopts decision 0005 point 4 as a requirement.** `UserResourceManager` hides users who are administrators through a group from every non-superuser identity, matching the direct-administrator rule, with superuser decided from the identity as WP-0h does. One place covers every user item route (`DELETE`, `/force`, `PATCH`, `/roles`, `/reset_password`, `/password`, `/generate_api_token`, `/ownership`, `/can_export_data`, `/is_user_in_group`) and the list the pickers use. The WP-0j grant-subset guard stays for targets who hold more than the caller but are not administrators. INV-3 rows 3 to 5 from the rating go into WP-0j's table; WP-0j's admin-through-group refusal cases move from 403 to 404; qa flips the WP-2b list-visibility pin.
2. **Option (a), a same-subset refusal on delete, deactivate and every removal, is not taken**: it would change many more outcomes (non-superuser managers could no longer offboard dashboard authors or members of groups they are not in) across about seven routes.
3. **WP-0k gains a unit: deactivated accounts are refused everywhere.** Password login, header login, the session cookie, API tokens and render tokens all refuse an account whose status is not active; the token-validity cache is invalidated on deactivation. INV-3 rows record each path (before: 200; after: 401), and the WP records that any existing integration relying on a deactivated account's token stops working. WP-0k is the right home because it already changes sign-in and token binding.
4. **Residuals, each Low, owned by WP-5d:** lesser roles removing peers or higher non-admin users; force-delete destroying dashboards the caller cannot delete directly; removing a user from a group the caller is not in; self force-delete through `/force`; no audit line for successful destructive user operations.

## What a human must accept

- No deployment needs a non-superuser to see, share with, or maintain administrator accounts; offboarding an administrator becomes a superuser or shell task, and the recovery path (`scripts/create_user.py --site_admin`) is documented per deployment.
- Deactivated accounts lose access immediately, including existing tokens.

## Consequences

- WP-0j's human-acceptance item and its "UserResourceManager: not adopted" section are rewritten; decision 0005 point 4 reads "adopted by decision 0010".
- WP-0k's INV-3 table grows by the inactive-account rows; it is merged together with WP-0j as already decided.
