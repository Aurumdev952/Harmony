'''Resource, group and user names, through the live API (WP-0l, decision 0012).

Before WP-0l the data-access layer matched a name case-insensitively with
`ILIKE`, so `_` and `%` in a name were wildcards, and of several matches
Postgres returned the row stored first. Each test stores the look-alike
first, the order that shows the wrong row; docstrings give the behaviour
before and after WP-0l (SPEC INV-3 rows of decision 0012). Each test deletes
what it creates through the admin session.
'''

from __future__ import annotations

import secrets
from contextlib import ExitStack

import pytest

from tests.authz.http.stack import USER_DOMAIN

# What `POST /api2/dashboard` needs to build a dashboard (tests/contract/cases).
_COMMON_SETTINGS = {
    'filterSettings': {
        'enabledCategories': [],
        'excludedTiles': [],
        'items': [],
        'visible': False,
        'enabledFilterHierarchy': [],
    },
    'groupingSettings': {
        'enabledCategories': [],
        'excludedTiles': [],
        'items': [],
        'visible': False,
    },
    'panelAlignment': 'LEFT',
}


def _specification(title: str) -> dict:
    return {
        'version': '2023-06-30',
        'items': [],
        'options': {'title': title, 'columnCount': 100},
        'commonSettings': _COMMON_SETTINGS,
        'legacy': False,
    }


@pytest.fixture(name='tag')
def fixture_tag() -> str:
    return secrets.token_hex(4)


@pytest.fixture(name='cleanup')
def fixture_cleanup():
    with ExitStack() as stack:
        yield stack


class Dashboard:
    '''A dashboard and its authorisation resource. The resource name is the
    slug with every separator turned into `_`.'''

    def __init__(self, stack, session, slug: str, cleanup: ExitStack) -> None:
        response = stack.request(
            session,
            'POST',
            '/api2/dashboard',
            {'slug': slug, 'specification': _specification(slug)},
        )
        assert response.status_code == 200, response.text[:500]
        body = response.json()
        self.uri = body['$uri']
        self.resource_uri = body['resource']
        self.slug = slug
        cleanup.callback(_delete, stack, self.uri)

    def rename(self, stack, session, title: str) -> None:
        response = stack.request(
            session,
            'PATCH',
            self.uri,
            {'slug': self.slug, 'specification': _specification(title)},
        )
        assert response.status_code == 200, response.text[:500]

    def holders(self, stack) -> dict:
        roles = stack.admin_json('GET', f'{self.resource_uri}/roles')
        return {
            'users': {name: sorted(r) for name, r in roles['userRoles'].items()},
            'groups': {name: sorted(r) for name, r in roles['groupRoles'].items()},
        }


def _delete(stack, uri: str) -> None:
    response = stack.request(stack.admin, 'DELETE', uri)
    # Admin DELETE /api2/role returns 200; other resources return 204.
    assert response.status_code in (200, 204, 404), (uri, response.status_code)


def _account(stack, local_part: str) -> str:
    '''Creates `<local_part>@authz.invalid` with no password or roles.'''
    username = f'{local_part}@{USER_DOMAIN}'
    user = stack.admin_json(
        'POST',
        '/api2/user',
        {
            'username': username,
            'firstName': 'Authz',
            'lastName': 'Name matching',
            'phoneNumber': '',
            'status': 'active',
        },
    )
    stack.created_users.add(user['$uri'])
    return username


def _share(stack, session, dashboard: Dashboard, users: dict, groups: dict):
    return stack.request(
        session,
        'POST',
        f'{dashboard.resource_uri}/roles',
        {
            'userRoles': users,
            'groupRoles': groups,
            'sitewideResourceAcl': {
                'registeredResourceRole': '',
                'unregisteredResourceRole': '',
            },
        },
    )


def _acl(role_name: str, resource_name: str) -> dict:
    return {
        '$uri': '',
        'resourceRole': {'$uri': '', 'name': role_name, 'resourceType': 'DASHBOARD'},
        'resource': {
            '$uri': '',
            'label': resource_name,
            'name': resource_name,
            'resourceType': 'DASHBOARD',
        },
    }


def _resource_name(slug: str) -> str:
    return slug.replace(' ', '_').replace('-', '_')


def _patch_user(stack, username: str, acls=(), groups=()) -> None:
    '''Sets a user's ACLs and groups through `PATCH /api2/user/<id>`, which
    resolves groups by URI, so the setup itself never matches a username.'''
    user = stack.find_user(username)
    stack.admin_json(
        'PATCH',
        user['$uri'],
        {
            '$uri': user['$uri'],
            'username': username,
            'firstName': user['firstName'],
            'lastName': user['lastName'],
            'phoneNumber': '',
            'status': 'active',
            'acls': list(acls),
            'apiTokens': [],
            'roles': [],
            'groups': list(groups),
        },
    )


def _group(stack, name: str, cleanup: ExitStack, acls=()) -> str:
    stack.admin_json(
        'POST',
        '/api2/group',
        {'$uri': '', 'name': name, 'roles': [], 'users': [], 'acls': list(acls)},
    )
    uri = next(
        g['$uri']
        for g in stack.admin_json('GET', '/api2/group?per_page=1000')
        if g['name'] == name
    )
    cleanup.callback(_delete, stack, uri)
    return uri


def _members(stack, group_uri: str) -> list:
    return sorted(
        user['username'] for user in stack.admin_json('GET', group_uri)['users']
    )


def _role(stack, label: str, cleanup: ExitStack) -> str:
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
    cleanup.callback(_delete, stack, role['$uri'])
    return role['$uri']


def _role_uris_of(stack, username: str) -> list:
    return [role['$uri'] for role in stack.find_user(username)['roles']]


# Path A: a dashboard's own name is looked up again as a pattern.


def test_creating_a_dashboard_makes_its_author_admin_of_that_dashboard_only(
    stack, tag, cleanup
):
    '''Before: the author (`_default_role`, which may create dashboards)
    became dashboard_admin of the look-alike the admin made earlier, which it
    could not even view, and held nothing on its own new dashboard. After:
    dashboard_admin of its own dashboard only.'''
    author = stack.ensure_user(f'0l-creator-{tag}', ['_default_role'])
    author_name = author.headers['X-Username']
    look_alike = Dashboard(stack, stack.admin, f'qa0l axb {tag}', cleanup)
    created = Dashboard(stack, author, f'qa0l a b {tag}', cleanup)

    assert {
        'created': created.holders(stack)['users'].get(author_name),
        'look-alike': look_alike.holders(stack)['users'].get(author_name),
    } == {'created': ['dashboard_admin'], 'look-alike': None}


def test_sharing_a_dashboard_stores_every_acl_on_that_dashboard(stack, tag, cleanup):
    '''The author makes `qa0l_a_b_<tag>`, the admin then makes the look-alike
    `qa0l_axb_<tag>`, and the author retitles its dashboard twice. A save
    writes the resource label from the title before the save, so the second
    one rewrites the resource row, after the look-alike's (probed with
    `ctid`; one save leaves the row in place). Before: sharing stored the
    author's dashboard_admin and the viewer's dashboard_viewer on the
    look-alike, and the author lost dashboard_admin on its own dashboard.
    After: both are stored on the author's dashboard; the look-alike keeps
    only the admin.'''
    author = stack.ensure_user(f'0l-sharer-{tag}', ['_default_role'])
    author_name = author.headers['X-Username']
    viewer = _account(stack, f'0l-viewer-{tag}')
    named = Dashboard(stack, author, f'qa0l a b {tag}', cleanup)
    look_alike = Dashboard(stack, stack.admin, f'qa0l axb {tag}', cleanup)
    look_alike_before = look_alike.holders(stack)
    named.rename(stack, author, f'qa0l a b {tag} retitled')
    named.rename(stack, author, f'qa0l a b {tag} retitled twice')

    response = _share(
        stack,
        author,
        named,
        {author_name: ['dashboard_admin'], viewer: ['dashboard_viewer']},
        {},
    )

    assert response.status_code == 204, response.text[:500]
    assert {
        'named': named.holders(stack)['users'],
        'look-alike': look_alike.holders(stack),
    } == {
        'named': {author_name: ['dashboard_admin'], viewer: ['dashboard_viewer']},
        'look-alike': look_alike_before,
    }


# Path B: a share is removed by user or group name, matched as a pattern.


def test_removing_a_users_share_keeps_a_look_alike_users_share(stack, tag, cleanup):
    '''Before: removing `john_doe`'s share deleted `john.doe`'s, and
    `john_doe` kept dashboard_viewer. After: exactly `john_doe`'s share goes.'''
    author = stack.ensure_user(f'0l-remover-{tag}', ['_default_role'])
    author_name = author.headers['X-Username']
    dashboard = Dashboard(stack, author, f'qa0l users {tag}', cleanup)
    look_alike = _account(stack, f'john.doe-{tag}')
    named = _account(stack, f'john_doe-{tag}')
    viewer_acl = _acl('dashboard_viewer', _resource_name(dashboard.slug))
    for username in (look_alike, named):
        _patch_user(stack, username, acls=[viewer_acl])
    assert dashboard.holders(stack)['users'] == {
        author_name: ['dashboard_admin'],
        look_alike: ['dashboard_viewer'],
        named: ['dashboard_viewer'],
    }

    response = _share(
        stack,
        author,
        dashboard,
        {author_name: ['dashboard_admin'], look_alike: ['dashboard_viewer']},
        {},
    )

    assert response.status_code == 204, response.text[:500]
    assert dashboard.holders(stack)['users'] == {
        author_name: ['dashboard_admin'],
        look_alike: ['dashboard_viewer'],
    }


@pytest.mark.parametrize(
    'names',
    [('team_a', 'teamxa'), ('team%a', 'team-q-a')],
    ids=['underscore', 'percent'],
)
def test_removing_a_groups_share_keeps_a_look_alike_groups_share(
    stack, tag, cleanup, names
):
    '''Before: removing the named group's share deleted the look-alike's, and
    the named group kept dashboard_viewer. After: exactly the named group's
    share goes.'''
    named, look_alike = (f'qa0l-{name}-{tag}' for name in names)
    author = stack.ensure_user(f'0l-group-remover-{tag}', ['_default_role'])
    author_name = author.headers['X-Username']
    dashboard = Dashboard(stack, author, f'qa0l groups {tag}', cleanup)
    viewer_acl = _acl('dashboard_viewer', _resource_name(dashboard.slug))
    for name in (look_alike, named):
        _group(stack, name, cleanup, acls=[viewer_acl])
    assert dashboard.holders(stack)['groups'] == {
        look_alike: ['dashboard_viewer'],
        named: ['dashboard_viewer'],
    }

    response = _share(
        stack,
        author,
        dashboard,
        {author_name: ['dashboard_admin']},
        {look_alike: ['dashboard_viewer']},
    )

    assert response.status_code == 204, response.text[:500]
    assert dashboard.holders(stack)['groups'] == {look_alike: ['dashboard_viewer']}


def test_removing_every_group_share_leaves_no_group_holding_the_dashboard(
    stack, tag, cleanup
):
    '''An empty `groupRoles` removes each group by name. Before: the named
    group `team_a` kept its share. After: no group holds the dashboard.'''
    author = stack.ensure_user(f'0l-group-clearer-{tag}', ['_default_role'])
    author_name = author.headers['X-Username']
    dashboard = Dashboard(stack, author, f'qa0l clear {tag}', cleanup)
    viewer_acl = _acl('dashboard_viewer', _resource_name(dashboard.slug))
    for name in (f'qa0l-teamxa-{tag}', f'qa0l-team_a-{tag}'):
        _group(stack, name, cleanup, acls=[viewer_acl])

    response = _share(stack, author, dashboard, {author_name: ['dashboard_admin']}, {})

    assert response.status_code == 204, response.text[:500]
    assert dashboard.holders(stack)['groups'] == {}


# Path D: group and role membership by username, matched as a pattern.


def test_adding_a_user_to_a_group_by_username_adds_that_user(stack, tag, cleanup):
    '''Before: `john.doe` joined the group. After: `john_doe` does.'''
    look_alike = _account(stack, f'john.doe-{tag}')
    named = _account(stack, f'john_doe-{tag}')
    group_uri = _group(stack, f'qa0l-members-{tag}', cleanup)

    response = stack.request(stack.admin, 'POST', f'{group_uri}/users', named)

    assert response.status_code in (200, 201), response.text[:500]
    assert _members(stack, group_uri) == [named]
    assert look_alike not in _members(stack, group_uri)


def test_deleting_a_user_from_a_group_by_username_removes_that_user(
    stack, tag, cleanup
):
    '''Before: `john.doe` left the group and `john_doe` stayed. After:
    `john_doe` leaves.'''
    look_alike = _account(stack, f'john.doe-{tag}')
    named = _account(stack, f'john_doe-{tag}')
    group_uri = _group(stack, f'qa0l-members-{tag}', cleanup)
    for username in (look_alike, named):
        _patch_user(stack, username, groups=[group_uri])
    assert _members(stack, group_uri) == sorted([look_alike, named])

    response = stack.request(stack.admin, 'DELETE', f'{group_uri}/users', named)

    assert response.status_code == 200, response.text[:500]
    assert _members(stack, group_uri) == [look_alike]


def test_setting_a_roles_users_by_username_adds_those_users(stack, tag, cleanup):
    '''Before: `john.doe` received the role. After: `john_doe` does.'''
    look_alike = _account(stack, f'john.doe-{tag}')
    named = _account(stack, f'john_doe-{tag}')
    role_uri = _role(stack, f'qa0l members {tag}', cleanup)

    response = stack.request(stack.admin, 'PATCH', f'{role_uri}/users', [named])

    assert response.status_code == 200, response.text[:500]
    assert {
        'named': role_uri in _role_uris_of(stack, named),
        'look-alike': role_uri in _role_uris_of(stack, look_alike),
    } == {'named': True, 'look-alike': False}


def test_a_username_only_a_look_alike_matches_is_not_found(stack, tag, cleanup):
    '''INV-3 (decision 0012): a name with `_` and no exact match is a 404.
    Before: 201 and `john.doe` joined the group.'''
    look_alike = _account(stack, f'john.doe-{tag}')
    group_uri = _group(stack, f'qa0l-members-{tag}', cleanup)

    response = stack.request(
        stack.admin, 'POST', f'{group_uri}/users', f'john_doe-{tag}@{USER_DOMAIN}'
    )

    assert response.status_code == 404, response.text[:500]
    assert look_alike not in _members(stack, group_uri)


# Path C: the 403 for an ACL grant repeated the matched dashboard's real name.


def _moderated_group(stack, tag: str, cleanup: ExitStack):
    name = f'qa0l-grants-{tag}'
    group_uri = _group(stack, name, cleanup)
    actor = stack.ensure_user(f'0l-moderator-{tag}', ['group_moderator'], [group_uri])
    return actor, name, group_uri


def _grant_to_group(stack, actor, name: str, group_uri: str, resource_name: str):
    return stack.request(
        actor,
        'PATCH',
        group_uri,
        {
            '$uri': group_uri,
            'name': name,
            'roles': [],
            'users': [actor.headers['X-Username']],
            'acls': [_acl('dashboard_viewer', resource_name)],
        },
    )


def test_a_refused_acl_grant_does_not_name_the_dashboard(stack, tag, cleanup):
    '''Before: 403 "Granting 'dashboard_viewer' on DASHBOARD '<name>' needs
    ...". After: a 403 that names no dashboard.'''
    private = Dashboard(stack, stack.admin, f'qa0l private {tag}', cleanup)
    actor, name, group_uri = _moderated_group(stack, tag, cleanup)
    resource_name = _resource_name(private.slug)

    response = _grant_to_group(stack, actor, name, group_uri, resource_name)

    assert response.status_code == 403
    assert resource_name not in response.text
    assert private.holders(stack)['groups'] == {}


def test_an_acl_naming_a_pattern_does_not_reveal_the_dashboard_it_matches(
    stack, tag, cleanup
):
    '''Before: `qa0l_a_b_<tag>` matched `qa0l_axb_<tag>`, which the caller
    cannot list, and the 403 named it. After: the grant is refused or not
    found, and the body names no dashboard.'''
    hidden = Dashboard(stack, stack.admin, f'qa0l axb {tag}', cleanup)
    actor, name, group_uri = _moderated_group(stack, tag, cleanup)

    response = _grant_to_group(
        stack, actor, name, group_uri, _resource_name(f'qa0l a b {tag}')
    )

    assert response.status_code in (403, 404)
    assert _resource_name(hidden.slug) not in response.text
    assert hidden.holders(stack)['groups'] == {}
