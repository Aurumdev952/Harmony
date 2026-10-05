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
        .order_by(User.id)
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


def username_taken(
    username: str,
    session: Optional[Session] = None,
    except_user_id: Optional[int] = None,
) -> bool:
    '''Whether another account's username equals `username` ignoring case.

    Accounts that differ only by case make sign-in ambiguous, so no new account
    or rename may add one.
    '''
    if not username:
        return False
    return any(
        user.id != except_user_id for user in _equal_ignoring_case(username, session)
    )
