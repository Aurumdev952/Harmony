from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.alchemy.user import User, UserStatusEnum
from web.server.data.data_access import get_db_adapter


def _equal_ignoring_case(username: str, session: Optional[Session]) -> List[User]:
    session = session or get_db_adapter().session
    return (
        session.query(User)
        .filter(func.lower(User.username) == func.lower(username))
        .all()
    )


def find_user_by_username(
    username: Optional[str], session: Optional[Session] = None
) -> Optional[User]:
    '''The account `username` names, or None.

    Usernames compare equal ignoring case, never as a LIKE pattern, so `_` and
    `%` are literal: `john_doe` does not find `john.doe`. Usernames are unique
    only as stored, so several accounts can be equal ignoring case. Active
    accounts come first, then the rest (pending invitations, deactivated
    accounts); within the first group that has any, the exact spelling wins,
    else its only account, else nobody rather than an arbitrary one.
    '''
    if not username:
        return None
    candidates = _equal_ignoring_case(username, session)
    active = [
        user for user in candidates if user.status_id == UserStatusEnum.ACTIVE.value
    ]
    rest = [
        user for user in candidates if user.status_id != UserStatusEnum.ACTIVE.value
    ]
    for group in (active, rest):
        if not group:
            continue
        exact = [user for user in group if user.username == username]
        if exact:
            return exact[0]
        return group[0] if len(group) == 1 else None
    return None


def find_named_account(
    username: Optional[str], session: Optional[Session] = None
) -> Optional[User]:
    '''The account a caller names as a target (role or group membership,
    transfers, role assignment): the exact spelling, whatever its status; else
    the one account equal to it ignoring case; else None. Sign-in's preference
    for active accounts would pick a twin the caller did not name.
    '''
    if not username:
        return None
    candidates = _equal_ignoring_case(username, session)
    exact = [user for user in candidates if user.username == username]
    if exact:
        return exact[0]
    return candidates[0] if len(candidates) == 1 else None


def find_legacy_token_account(
    username: Optional[str], session: Optional[Session] = None
) -> Optional[User]:
    '''The account a session issued before WP-0k can mean, or None.

    Such a session names the string the user typed, and before WP-0k sign-in
    took the first account that string matched as an ILIKE pattern (`_` and
    `%` wildcards, any case). So the session can only be trusted when that
    pattern matches exactly one account that is not a pending invitation
    (pending accounts never signed in): typing `john_doe` with `john.doe`'s
    password made a session naming `john_doe`, which must not sign in a
    `john_doe` account that never gave a password.
    '''
    if not username:
        return None
    session = session or get_db_adapter().session
    candidates = (
        session.query(User)
        .filter(
            User.username.ilike(username),
            User.status_id != UserStatusEnum.PENDING.value,
        )
        .limit(2)
        .all()
    )
    return candidates[0] if len(candidates) == 1 else None


def username_taken(
    username: str,
    session: Optional[Session] = None,
    except_user_id: Optional[int] = None,
    ignore_pending: bool = False,
) -> bool:
    '''Whether another account's username equals `username` ignoring case.
    With `ignore_pending`, pending invitations do not count.

    Accounts that differ only by case make sign-in ambiguous, so no new account,
    rename or registration may add one.
    '''
    if not username:
        return False
    return any(
        user.id != except_user_id
        and not (ignore_pending and user.status_id == UserStatusEnum.PENDING.value)
        for user in _equal_ignoring_case(username, session)
    )
