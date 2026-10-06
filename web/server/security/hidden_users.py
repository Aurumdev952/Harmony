'''Users hidden from the caller (decision 0010).

Administrators, direct or through a group, are hidden from every identity that
is not a superuser, as if they did not exist: `UserResourceManager` leaves them
out of the user list and every user item route, and the helpers below apply the
same rule where other code names or looks up users. "Superuser" is the
identity, never the account, as in `web.server.security.grants`.
'''

from flask import request
from flask_login import current_user
from sqlalchemy import or_

from models.alchemy.permission import Role
from models.alchemy.security_group import Group
from models.alchemy.user import User
from web.server.data.data_access import get_db_adapter
from web.server.security.permissions import SUPERUSER_ROLENAME, SuperUserPermission


def administrators():
    '''A filter on `User`: holds the admin role directly or through a group.'''
    is_admin = Role.name == SUPERUSER_ROLENAME
    return or_(User.roles.any(is_admin), User.groups.any(Group.roles.any(is_admin)))


def _hidden_users() -> dict:
    '''Ids and usernames of the users hidden from the caller: none for a
    superuser. One query per request, however many items a list formats.
    '''
    if SuperUserPermission().can():
        return {}
    hidden = request.environ.get('harmony.hidden_users')
    if hidden is None:
        session = get_db_adapter().session
        hidden = dict(session.query(User.id, User.username).filter(administrators()))
        request.environ['harmony.hidden_users'] = hidden
    return hidden


def visible_username(username):
    '''`username`, or None when its user is hidden from the caller. For fields
    that name a user outside the user routes, such as a dashboard's author.
    '''
    if username in _hidden_users().values():
        return None
    return username


def is_hidden_from_caller(user) -> bool:
    '''Whether `user` is hidden from the caller. The caller always sees itself,
    so a narrowed admin token can still name its own account.
    '''
    return user.id != current_user.id and user.id in _hidden_users()
