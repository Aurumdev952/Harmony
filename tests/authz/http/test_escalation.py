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


def test_group_admin_becomes_site_admin_by_creating_a_group_with_the_admin_role(
    stack, tag
):
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
        stack.admin_json('DELETE', _group_uri(stack, name))


def test_group_moderator_becomes_site_admin_through_a_group_it_belongs_to(stack, tag):
    name = f'authz-moderated-{tag}'
    stack.admin_json(
        'POST',
        '/api2/group',
        {'$uri': '', 'name': name, 'roles': [], 'users': [], 'acls': []},
    )
    group_uri = _group_uri(stack, name)
    try:
        actor = stack.ensure_user(
            'esc-group-moderator', ['group_moderator'], [group_uri]
        )
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
    finally:
        stack.admin_json('DELETE', group_uri)


def test_role_administrator_grants_itself_any_permission_through_a_new_role(stack, tag):
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
