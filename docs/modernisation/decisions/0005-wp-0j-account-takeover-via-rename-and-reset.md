# 0005. Add WP-0j: refuse username changes and password resets that reach a higher-privileged account

Status: applied by the lead on 2026-10-05, pending human ratification (SPEC section 10).

## Context

The WP-0h security re-review (round 2, at `dc65f70`) confirmed live, on base and branch, the finding first raised at round 1 as H5:

- A non-superuser holding `manager` plus `user_admin` can `PATCH /api2/user/<id>` and change the `username` of a user who is an administrator through a group. The request returns 200; the target's groups are kept by WP-0h's resend rule, so the target stays an administrator under the attacker's address.
- The same caller can then `POST /api2/user/<id>/reset_password` (204). `send_reset_password` is handed the new username, so the reset link goes to the attacker, who takes over the administrator account.

WP-0h's scope (decision 0004 rule 1) covers grants a caller confers; a rename and a reset are not grants, so WP-0h correctly left this open. The combination is a real production role set and needs no narrowed token.

## Decision

1. **WP-0j: Refuse username changes and password resets of users whose grants exceed the caller's** is added to SPEC section 5: owner `backend`, supporting `security, qa`, depends on `0h`, Sec yes.
2. Rule: a non-superuser may change the `username` of, or trigger a password reset for, only a user whose grants are a subset of the caller's own. Grants are roles (direct or through a group), group memberships, ACLs, query policies and data export; administrator by any path counts. Refusals are 403, write nothing and leave an audit line. Superusers are unchanged.
3. The behaviour change is recorded as an INV-3 row accepted by security and the human:

   | Principal | Request | Before | After |
   |---|---|---|---|
   | non-superuser with `manager` + `user_admin` | `PATCH /api2/user/<id>` changing `username`, or `POST /api2/user/<id>/reset_password`, of a user holding grants the caller does not hold | 200 / 204; username changed; reset mailed to the new address | 403; nothing written; audit line |

4. Adopted as a requirement by decision 0010: `UserResourceManager` also hides users who are administrators through a group from non-superusers, matching its existing direct-administrator rule; if adopted it gets its own INV-3 row.
5. WP-2b pins today's behaviour; WP-0j flips the pins in its own stack, by qa.

## Consequences

- SPEC 1.5: WP-0j row; phase 0 gains section 0j.
- WP-0h is not held for this; its remaining item is the `member_groups_from_uris` admin-group exclusion.
