'''Grants that change what a principal can do, recorded as they behave on main.

Several of these are privilege escalations (WP-2b "Findings for security").
They are pinned so that fixing one is a deliberate, security-reviewed change
to this file (SPEC INV-3), never a silent one. Every test cleans up what it
creates through the admin session.
'''

from __future__ import annotations

import secrets

import pytest

from tests.authz.http.stack import outcome


@pytest.fixture(name='tag')
def fixture_tag() -> str:
    return secrets.token_hex(4)


def _group_uri(stack, name):
    groups = stack.admin_json('GET', '/api2/group?per_page=100')
    return next(g['$uri'] for g in groups if g['name'] == name)


@pytest.fixture(name='empty_group')
def fixture_empty_group(stack, tag):
    '''A fresh group the admin owns, deleted afterwards.'''
    name = f'authz-group-{tag}'
    stack.admin_json(
        'POST',
        '/api2/group',
        {'$uri': '', 'name': name, 'roles': [], 'users': [], 'acls': []},
    )
    uri = _group_uri(stack, name)
    try:
        yield name, uri
    finally:
        stack.admin_json('DELETE', uri)


def test_group_admin_becomes_site_admin_by_creating_a_group_with_the_admin_role(
    stack, tag
):
    '''H1: defect pinned as today; flips in WP-0h.'''
    actor = stack.ensure_user('esc-group-admin', ['group_admin'])
    admin_role = stack.roles_by_name()['admin']
    name = f'authz-escalation-{tag}'
    assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:unauthorizedPage'

    created = stack.request(
        actor,
        'POST',
        '/api2/group',
        {'$uri': '', 'name': name, 'roles': [admin_role], 'users': [], 'acls': []},
    )
    try:
        assert created.status_code == 200
        assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:admin'
    finally:
        stack.delete_group_named(name)


def test_group_moderator_becomes_site_admin_through_a_group_it_belongs_to(
    stack, empty_group
):
    '''H2: defect pinned as today; flips in WP-0h.'''
    name, group_uri = empty_group
    actor = stack.ensure_user('esc-group-moderator', ['group_moderator'], [group_uri])
    assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:unauthorizedPage'

    updated = stack.request(
        actor,
        'PATCH',
        group_uri,
        {
            '$uri': group_uri,
            'name': name,
            'roles': [stack.roles_by_name()['admin']],
            'users': [actor.headers['X-Username']],
            'acls': [],
        },
    )
    assert updated.status_code == 200
    assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:admin'


def test_group_moderator_gains_all_values_policies_by_attaching_a_role(
    stack, empty_group
):
    '''N5: defect pinned as today; flips in WP-0h. _default_role carries the
    seeded all-values query policies.'''
    name, group_uri = empty_group
    actor = stack.ensure_user('esc-group-mod-policy', ['group_moderator'], [group_uri])

    updated = stack.request(
        actor,
        'PATCH',
        group_uri,
        {
            '$uri': group_uri,
            'name': name,
            'roles': [stack.roles_by_name()['_default_role']],
            'users': [actor.headers['X-Username']],
            'acls': [],
        },
    )
    assert updated.status_code == 200
    policies = {
        p['dimension']
        for p in stack.admin_json('GET', '/api2/query_policy?per_page=100')
    }
    assert {'source', 'StateName'} <= policies


def test_group_moderator_cannot_reach_a_group_it_is_not_a_member_of(stack, tag):
    '''The "/users self-add" vector decision 0004 lists is not reachable: the
    item routes resolve the group through GroupResourceManager._query, which
    filters to the caller's own groups, so a non-member moderator gets 404
    before the sitewide edit_resource check. The reachable group_moderator ->
    admin path is a member editing its group's roles (H2 / N5). Pinned so WP-0h
    knows the 404 is the owner filter, not an authorisation refusal.'''
    name = f'authz-adminheld-{tag}'
    stack.admin_json(
        'POST',
        '/api2/group',
        {
            '$uri': '',
            'name': name,
            'roles': [stack.roles_by_name()['admin']],
            'users': [],
            'acls': [],
        },
    )
    group_uri = _group_uri(stack, name)
    try:
        actor = stack.ensure_user('esc-self-add', ['group_moderator'])
        added = stack.request(
            actor, 'POST', f'{group_uri}/users', actor.headers['X-Username']
        )
        assert added.status_code == 404
        assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:unauthorizedPage'
    finally:
        stack.admin_json('DELETE', group_uri)


def test_role_moderator_adds_a_permission_to_a_role_it_holds(stack, tag):
    '''N3: defect pinned as today; flips in WP-0h.'''
    label = f'authz rolemod {tag}'
    role = stack.admin_json(
        'POST',
        '/api2/role',
        {
            '$uri': '',
            'name': '',
            'label': label,
            'alertResourceRoleName': '',
            'dashboardResourceRoleName': '',
            'permissions': [],
            'queryPolicies': [],
            'dataExport': False,
        },
    )
    role_uri = role['$uri']
    try:
        actor = stack.ensure_user(
            'esc-role-mod', ['role_moderator', label.replace(' ', '_')]
        )
        assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:unauthorizedPage'

        updated = stack.request(
            actor,
            'PATCH',
            role_uri,
            {
                '$uri': role_uri,
                'name': role['name'],
                'label': label,
                'alertResourceRoleName': '',
                'dashboardResourceRoleName': '',
                'permissions': [
                    {'permission': 'view_admin_page', 'resource_type_id': 1}
                ],
                'queryPolicies': [],
                'dataExport': False,
            },
        )
        assert updated.status_code == 200
        assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:admin'
    finally:
        stack.admin_json('DELETE', role_uri)


def test_role_administrator_attaches_all_values_policies_and_data_export(stack, tag):
    '''N4: defect pinned as today; flips in WP-0h. build_role resolves query
    policy URIs with find_by_id, bypassing the resource filter.'''
    actor = stack.ensure_user('esc-role-admin-pol', ['role_administrator'])
    label = f'authz rolepolicy {tag}'

    created = stack.request(
        actor,
        'POST',
        '/api2/role',
        {
            '$uri': '',
            'name': '',
            'label': label,
            'alertResourceRoleName': '',
            'dashboardResourceRoleName': '',
            'permissions': [],
            'queryPolicies': [
                {
                    '$uri': '/api2/query_policy/1',
                    'dimension': 'source',
                    'dimensionValue': None,
                    'queryPolicyTypeId': 1,
                },
                {
                    '$uri': '/api2/query_policy/2',
                    'dimension': 'StateName',
                    'dimensionValue': None,
                    'queryPolicyTypeId': 2,
                },
            ],
            'dataExport': True,
        },
    )
    role_uri = None
    try:
        assert created.status_code == 200
        role = created.json()
        role_uri = role['$uri']
        assert role['dataExport'] is True
        assert {p['dimension'] for p in role['queryPolicies']} == {
            'source',
            'StateName',
        }
    finally:
        if role_uri:
            stack.admin_json('DELETE', role_uri)


def test_role_moderator_grants_a_role_it_holds_to_another_user(stack, tag):
    '''N6: defect pinned as today; flips in WP-0h.'''
    label = f'authz grantable {tag}'
    role = stack.admin_json(
        'POST',
        '/api2/role',
        {
            '$uri': '',
            'name': '',
            'label': label,
            'alertResourceRoleName': '',
            'dashboardResourceRoleName': '',
            'permissions': [{'permission': 'view_admin_page', 'resource_type_id': 1}],
            'queryPolicies': [],
            'dataExport': False,
        },
    )
    role_uri = role['$uri']
    try:
        actor = stack.ensure_user(
            'esc-role-granter', ['role_moderator', label.replace(' ', '_')]
        )
        target = stack.ensure_user('esc-grant-target', [])
        target_name = target.headers['X-Username']

        granted = stack.request(actor, 'PATCH', f'{role_uri}/users', [target_name])
        assert granted.status_code == 200
        # The moderator granted a role carrying view_admin_page to another user.
        # The target's identity is cached for up to 10 minutes (findings "H6
        # cache"), so verify the grant landed through the admin view rather than
        # the target's own request.
        role_now = stack.admin_json('GET', role_uri)
        assert target_name in role_now['usernames']
    finally:
        stack.admin_json('DELETE', role_uri)


def test_role_administrator_grants_itself_any_permission_through_a_new_role(stack, tag):
    '''H3: defect pinned as today; flips in WP-0h.'''
    actor = stack.ensure_user('esc-role-admin', ['role_administrator'])
    label = f'authz escalation {tag}'
    assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:unauthorizedPage'

    created = stack.request(
        actor,
        'POST',
        '/api2/role',
        {
            '$uri': '',
            'name': '',
            'label': label,
            'alertResourceRoleName': '',
            'dashboardResourceRoleName': 'dashboard_admin',
            'permissions': [{'permission': 'view_admin_page', 'resource_type_id': 1}],
            'queryPolicies': [],
            'dataExport': True,
        },
    )
    try:
        assert created.status_code == 200
        assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:admin'
    finally:
        role_uri = stack.roles_by_name().get(label.replace(' ', '_'))
        if role_uri:
            stack.admin_json('DELETE', role_uri)


def test_user_admin_cannot_change_roles_through_the_user_form(stack):
    '''Today's behaviour: PATCH user needs SITE edit_user, which user_admin
    lacks, so this is refused (401). WP-0h must keep it refused.'''
    actor = stack.ensure_user('esc-user-admin', ['user_admin'])
    target = stack.ensure_user('esc-target', [])
    uri = target.user_uri
    username = target.headers['X-Username']

    response = stack.request(
        actor,
        'PATCH',
        uri,
        {
            '$uri': uri,
            'username': username,
            'firstName': 'Authz',
            'lastName': 'esc-target',
            'phoneNumber': '',
            'status': 'active',
            'acls': [],
            'apiTokens': [],
            'roles': [stack.roles_by_name()['admin']],
            'groups': [],
        },
    )
    assert response.status_code == 401
    assert stack.find_user(username)['roles'] == []


def test_admin_cannot_delete_their_own_account(stack):
    admin = stack.role_user('admin')
    response = stack.request(admin, 'DELETE', admin.user_uri)
    assert response.status_code == 400
