from sqlalchemy import func

from models.alchemy.user import User
from web.server.data.data_access import get_db_adapter


def find_user_by_username(username, session=None):
    '''The user whose username equals `username`, ignoring case, or None.

    An equality on `lower(username)`, never a LIKE pattern, so `_` and `%` are
    literal: `john_doe` does not find `john.doe`. Usernames are unique only as
    stored, so an exact match wins, and when only case-insensitive matches exist
    and there is more than one, nobody matches rather than an arbitrary one.
    '''
    if not username:
        return None
    session = session or get_db_adapter().session
    exact = session.query(User).filter(User.username == username).first()
    if exact:
        return exact
    matches = (
        session.query(User)
        .filter(func.lower(User.username) == func.lower(username))
        .limit(2)
        .all()
    )
    return matches[0] if len(matches) == 1 else None
