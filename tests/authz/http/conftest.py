from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from tests.authz.http.stack import Stack

_HERE = os.path.dirname(__file__)


def pytest_collection_modifyitems(config, items):
    del config
    skip = pytest.mark.skip(reason='set AUTHZ_BASE_URL; see tests/authz/stack.sh')
    for item in items:
        if str(item.fspath).startswith(_HERE):
            item.add_marker(pytest.mark.authz_http)
            if not os.environ.get('AUTHZ_BASE_URL'):
                item.add_marker(skip)


@pytest.fixture(name='stack', scope='session')
def fixture_stack() -> Iterator[Stack]:
    stack = Stack.from_env()
    yield stack
    stack.cleanup()


@pytest.fixture(name='own_accounts')
def fixture_own_accounts(stack) -> Iterator[None]:
    '''Deletes the users and dashboards a test made when it ends. The account
    pins make over a hundred users, and the list pins read the first page
    (`per_page=100`) of `/api2/user`. Only for tests that never call
    `role_user`, whose users the session reuses.'''
    users, dashboards = set(stack.created_users), set(stack.created_dashboards)
    yield
    stack.cleanup(
        keep_users=users | {s.user_uri for s in stack._users.values()},
        keep_dashboards=dashboards,
    )
