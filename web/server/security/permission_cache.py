'''Clearing the memoized `User.get_permissions` after a change to what a user may do.

`get_permissions` memoizes the bound `_get_permissions` with flask-caching, which
keys each account's entry by the instance's `__caching_id__`, or `repr()` without
one. Clearing through the same memoized function uses that key, whichever it is.
'''

from flask import current_app

from models.alchemy.user.web_base_user import BaseWebUserMixin


def clear_permission_cache(user) -> None:
    '''Forget `user`'s cached permissions, so their next request reads them anew.'''
    user.get_permissions.delete_memoized()


def clear_every_permission_cache() -> None:
    '''Forget every account's cached permissions, after a change that reaches all
    of them, such as a sitewide resource role.'''
    # pylint: disable=protected-access
    current_app.cache.delete_memoized(BaseWebUserMixin._get_permissions)
