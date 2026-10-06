'''What Potion list endpoints return to each seeded role: the manager filters in
web/server/potion/managers.py and the principal list filter. The user list
showing all users (I1) and admins-via-group (H5, part of I1) are today's
behaviour; owners I1 WP-5d, H5 WP-5d.'''

from __future__ import annotations

import pytest

from tests.authz.principals import SEED

NON_ADMIN_ROLES = [name for name in SEED['roles'] if name != 'admin']
ADMIN_ONLY_LISTS = [
    '/api2/user_acl',
    '/api2/group_acl',
    '/api2/resource_role',
    '/api2/resource-type',
]


def _get(stack, session, path):
    response = stack.request(session, 'GET', f'{path}?per_page=100')
    assert response.status_code == 200, (path, response.status_code)
    return response.json()


def test_admin_sees_every_role_and_admin_only_list(stack):
    admin = stack.role_user('admin')
    assert set(SEED['roles']) <= {r['name'] for r in _get(stack, admin, '/api2/role')}
    assert len(_get(stack, admin, '/api2/resource_role')) == len(SEED['resource_roles'])
    assert len(_get(stack, admin, '/api2/resource-type')) == 6
    assert any(
        'admin' in {r['name'] for r in user['roles']}
        for user in _get(stack, admin, '/api2/user')
    )


@pytest.mark.parametrize('role', NON_ADMIN_ROLES)
def test_role_list_shows_only_roles_held(role, stack):
    session = stack.role_user(role)
    assert [r['name'] for r in _get(stack, session, '/api2/role')] == [role]


@pytest.mark.parametrize('role', NON_ADMIN_ROLES)
def test_user_list_hides_admins_but_shows_everyone_else(role, stack):
    session = stack.role_user(role)
    stack.role_user('dashboard_viewer')
    users = _get(stack, session, '/api2/user')
    role_sets = [{r['name'] for r in user['roles']} for user in users]
    assert not any('admin' in roles for roles in role_sets)
    assert {'dashboard_viewer'} in role_sets
    assert len(users) > 1


@pytest.mark.parametrize('role', NON_ADMIN_ROLES)
def test_query_policy_list_shows_only_own_roles_policies(role, stack):
    session = stack.role_user(role)
    policies = _get(stack, session, '/api2/query_policy')
    expected = len(SEED['roles'][role].get('query_policies', []))
    assert len(policies) == expected


@pytest.mark.parametrize('role', NON_ADMIN_ROLES)
@pytest.mark.parametrize('path', ADMIN_ONLY_LISTS)
def test_admin_only_lists_are_empty(role, path, stack):
    assert _get(stack, stack.role_user(role), path) == []
