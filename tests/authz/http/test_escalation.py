'''Grants that change what a principal can do, through the live API.

WP-2b found several privilege escalations on main ("Findings for security")
and pinned them as they behaved. WP-0h closed ten of them; those pins now
assert the refusal, and each docstring gives the behaviour before and after
WP-0h (SPEC INV-3: the flip is a recorded, security-reviewed change, never a
silent one). N6 is unchanged by lead ruling and stays pinned as it is. Every
test cleans up what it creates through the admin session.
'''

from __future__ import annotations

import secrets

import pytest

from tests.authz.http.stack import outcome


@pytest.fixture(name='tag')
def fixture_tag() -> str:
    return secrets.token_hex(4)


# The seeded all-values policies. build_role resolves each entry by its $uri
# alone; the other keys are labels only, and which seeded policy gets id 1 or 2
# can differ between fresh stacks. Only the URIs matter, so the tests assert
# the set of URIs and dimensions, never which dimension an id carries.
ALL_VALUES_POLICIES = [
    {
        '$uri': '/api2/query_policy/1',
        'dimension': 'StateName',
        'dimensionValue': None,
        'queryPolicyTypeId': 2,
    },
    {
        '$uri': '/api2/query_policy/2',
        'dimension': 'source',
        'dimensionValue': None,
        'queryPolicyTypeId': 1,
    },
]


def _group_uri(stack, name):
    groups = stack.admin_json('GET', '/api2/group?per_page=100')
    return next(g['$uri'] for g in groups if g['name'] == name)


def _group_names(stack) -> list:
    return [g['name'] for g in stack.admin_json('GET', '/api2/group?per_page=100')]


def _group_role_uris(stack, group_uri) -> list:
    return [role['$uri'] for role in stack.admin_json('GET', group_uri)['roles']]


def _user_role_uris(stack, session) -> list:
    user = stack.find_user(session.headers['X-Username'])
    return [role['$uri'] for role in user['roles']]


def _own_policy_dimensions(stack, session) -> list:
    '''The query policies the caller can see of its own: the manager filter
    narrows a non-admin to the policies of the roles it holds, directly or
    through a group (QueryPolicyResourceManager, read from the DB per request).'''
    response = stack.request(session, 'GET', '/api2/query_policy?per_page=100')
    assert response.status_code == 200, response.text[:300]
    return sorted(policy['dimension'] for policy in response.json())


def _role_body(label, name='', permissions=(), query_policies=(), data_export=False):
    return {
        '$uri': '',
        'name': name,
        'label': label,
        'alertResourceRoleName': '',
        'dashboardResourceRoleName': '',
        'permissions': list(permissions),
        'queryPolicies': list(query_policies),
        'dataExport': data_export,
    }


def _delete_if_present(stack, uri) -> None:
    response = stack.request(stack.admin, 'DELETE', uri)
    # Admin DELETE /api2/role returns 200; other resources return 204.
    assert response.status_code in (200, 204, 404), (uri, response.status_code)


def _delete_role_labelled(stack, label) -> None:
    role_uri = stack.roles_by_name().get(label.replace(' ', '_'))
    if role_uri:
        stack.admin_json('DELETE', role_uri)


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


def test_group_admin_cannot_create_a_group_with_the_admin_role(stack, tag):
    '''H1, flipped by WP-0h (row 1). Before: 200, the creator became the new
    group's only member and opened /admin. After: 403, no group is written,
    and /admin stays the unauthorized page.'''
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
        assert created.status_code == 403
        assert name not in _group_names(stack)
        assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:unauthorizedPage'
    finally:
        stack.delete_group_named(name)


def test_group_moderator_cannot_attach_the_admin_role_to_a_group_it_belongs_to(
    stack, empty_group
):
    '''H2, flipped by WP-0h (row 2). Before: 200, the group carried the admin
    role and the member opened /admin. After: 403, the group's roles stay
    empty, and /admin stays the unauthorized page.'''
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
    assert updated.status_code == 403
    assert _group_role_uris(stack, group_uri) == []
    assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:unauthorizedPage'


def test_group_moderator_cannot_gain_all_values_policies_by_attaching_a_role(
    stack, empty_group
):
    '''N5, flipped by WP-0h (row 2). _default_role carries the seeded
    all-values query policies, which the group_moderator does not hold.
    Before: 200, the group carried _default_role and the actor's own policy
    list went from [] to [StateName, source]. After: 403, the group's roles
    stay empty and the actor's own policy list stays [].'''
    name, group_uri = empty_group
    actor = stack.ensure_user('esc-group-mod-policy', ['group_moderator'], [group_uri])
    default_role = stack.roles_by_name()['_default_role']
    assert _own_policy_dimensions(stack, actor) == []

    updated = stack.request(
        actor,
        'PATCH',
        group_uri,
        {
            '$uri': group_uri,
            'name': name,
            'roles': [default_role],
            'users': [actor.headers['X-Username']],
            'acls': [],
        },
    )
    assert updated.status_code == 403
    assert _group_role_uris(stack, group_uri) == []
    assert _own_policy_dimensions(stack, actor) == []


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


def test_role_moderator_cannot_add_a_permission_to_a_role_it_holds(stack, tag):
    '''N3, flipped by WP-0h (row 9). Before: 200, the held role gained
    view_admin_page and the moderator opened /admin. After: 403, the role's
    permissions stay empty, and /admin stays the unauthorized page.'''
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
        assert updated.status_code == 403
        assert stack.admin_json('GET', role_uri)['permissions'] == []
        assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:unauthorizedPage'
    finally:
        stack.admin_json('DELETE', role_uri)


def test_role_administrator_cannot_create_a_role_with_all_values_policies_and_export(
    stack, tag
):
    '''N4 (create), flipped by WP-0h (row 8). build_role resolved query-policy
    URIs with find_by_id, bypassing the resource filter. Before: 200, a role
    carrying both all-values policies and dataExport, with the creator added.
    After: 403 (the account holds neither policy and no exporting role), and
    no role is written.'''
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
            'queryPolicies': ALL_VALUES_POLICIES,
            'dataExport': True,
        },
    )
    try:
        assert created.status_code == 403
        assert label.replace(' ', '_') not in stack.roles_by_name()
        assert _own_policy_dimensions(stack, actor) == []
    finally:
        _delete_role_labelled(stack, label)


@pytest.mark.parametrize('actor_role', ['role_moderator', 'role_administrator'])
def test_role_editor_cannot_add_all_values_policies_and_export_to_a_held_role(
    stack, tag, actor_role
):
    '''N4 (update), flipped by WP-0h (row 10). update_role goes through the
    same build_role as create. Before: 200, the held role carried both seeded
    all-values policies and dataExport, and the holder's own policy list went
    from [] to [StateName, source]. After: 403, the role keeps no policies and
    dataExport off, and the holder's own policy list stays [].'''
    label = f'authz rolepatch {actor_role[:9]} {tag}'
    role = stack.admin_json('POST', '/api2/role', _role_body(label))
    role_uri = role['$uri']
    try:
        actor = stack.ensure_user(
            f'esc-patch-{actor_role}', [actor_role, label.replace(' ', '_')]
        )
        assert _own_policy_dimensions(stack, actor) == []

        updated = stack.request(
            actor,
            'PATCH',
            role_uri,
            {
                **_role_body(
                    label,
                    name=role['name'],
                    query_policies=ALL_VALUES_POLICIES,
                    data_export=True,
                ),
                '$uri': role_uri,
            },
        )
        assert updated.status_code == 403
        role_now = stack.admin_json('GET', role_uri)
        assert role_now['dataExport'] is False
        assert role_now['queryPolicies'] == []
        assert _own_policy_dimensions(stack, actor) == []
    finally:
        stack.admin_json('DELETE', role_uri)


def test_group_moderator_empty_role_map_unlinks_the_group_roles_and_keeps_them(
    stack, tag
):
    '''/roles empty map (decision 0004 point 3), flipped by WP-0h (row 6).
    update_group_roles_from_map called session.delete on each Role row the
    group held. Before: 200, the Role row was deleted (admin GET 404) and a
    bystander holding it directly lost it. After: 200, the group's roles are
    unlinked, the Role row stays (admin GET 200) and the bystander keeps it.'''
    label = f'authz doomed group {tag}'
    role_uri = stack.admin_json('POST', '/api2/role', _role_body(label))['$uri']
    group_name = f'authz-doomed-{tag}'
    stack.admin_json(
        'POST',
        '/api2/group',
        {'$uri': '', 'name': group_name, 'roles': [role_uri], 'users': [], 'acls': []},
    )
    group_uri = _group_uri(stack, group_name)
    role_name = label.replace(' ', '_')
    try:
        bystander = stack.ensure_user('esc-doomed-bystander', [role_name])
        actor = stack.ensure_user(
            'esc-doomed-group-mod', ['group_moderator'], [group_uri]
        )

        response = stack.request(actor, 'PATCH', f'{group_uri}/roles', {})
        assert response.status_code == 200
        assert stack.request(stack.admin, 'GET', role_uri).status_code == 200
        assert _group_role_uris(stack, group_uri) == []
        assert role_uri in _user_role_uris(stack, bystander)
    finally:
        stack.admin_json('DELETE', group_uri)
        _delete_if_present(stack, role_uri)


def test_user_admin_empty_role_map_unlinks_the_user_roles_and_keeps_them(stack, tag):
    '''/roles empty map (decision 0004 point 3), flipped by WP-0h (row 6).
    update_user_roles_from_map called session.delete on each Role row the
    target held. Before: 200, the Role row was deleted (admin GET 404) and a
    bystander holding it lost it. After: 200, the target's roles are unlinked,
    the Role row stays (admin GET 200) and the bystander keeps it.'''
    label = f'authz doomed user {tag}'
    role_uri = stack.admin_json('POST', '/api2/role', _role_body(label))['$uri']
    role_name = label.replace(' ', '_')
    try:
        bystander = stack.ensure_user('esc-doomed-user-bystander', [role_name])
        target = stack.ensure_user('esc-doomed-user-target', [role_name])
        actor = stack.ensure_user('esc-doomed-user-admin', ['user_admin'])

        response = stack.request(actor, 'PATCH', f'{target.user_uri}/roles', {})
        assert response.status_code == 200
        assert stack.request(stack.admin, 'GET', role_uri).status_code == 200
        assert _user_role_uris(stack, target) == []
        assert role_uri in _user_role_uris(stack, bystander)
    finally:
        _delete_if_present(stack, role_uri)


def test_role_moderator_grants_a_role_it_holds_to_another_user(stack, tag):
    '''N6: lead ruled no change under decision 0004 rule 1; pinned as current
    behaviour; residual on WP-0h's human acceptance list.'''
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


def test_role_administrator_cannot_grant_itself_a_permission_through_a_new_role(
    stack, tag
):
    '''H3, flipped by WP-0h (row 7). Before: 200, the new role carried
    view_admin_page, dashboard_admin and dataExport, the creator was added,
    and it opened /admin. After: 403, no role is written, and /admin stays the
    unauthorized page.'''
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
        assert created.status_code == 403
        assert label.replace(' ', '_') not in stack.roles_by_name()
        assert outcome(stack.request(actor, 'GET', '/admin')) == 'page:unauthorizedPage'
    finally:
        _delete_role_labelled(stack, label)


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
