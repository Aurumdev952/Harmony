'''WP-0l (decision 0012): resource, group and user names match exactly,
ignoring case, never as LIKE patterns.

`find_one_by_fields(..., case_sensitive=False)` turns a name into
`ILIKE <name>` and takes `.first()` with no ordering, so `_` and `%` in a
name match other rows, and which match comes back is whichever Postgres scans
first: in practice the row stored earlier. Each case runs with the look-alike
stored first, the order that shows the wrong row, and with the named row
stored first, which passes before and after the fix and shows that the
outcome depends on storage order alone.

Before WP-0l the look-alike-first cases fail: the ACL, the removal or the
membership lands on the look-alike (paths A, B and D of decision 0012).
'''

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from models.alchemy.permission import Resource, ResourceRole, ResourceTypeEnum, Role
from models.alchemy.security_group import Group, GroupAcl
from models.alchemy.user import User, UserAcl

ORDERS = ['look_alike_first', 'named_first']

# What `POST /api2/dashboard` needs to build a dashboard (tests/contract/cases).
_EMPTY_SPECIFICATION = {
    'version': '2023-06-30',
    'items': [],
    'options': {'title': 'Name matching', 'columnCount': 100},
    'commonSettings': {
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
    },
    'legacy': False,
}


@pytest.fixture(name='db')
def fixture_db(app):
    with app.app_context():
        yield app.extensions['sqlalchemy'].db


@pytest.fixture(name='tag')
def fixture_tag() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture(name='no_mail')
def fixture_no_mail(app, monkeypatch):
    '''Creating or sharing a dashboard mails a link to the dashboard page;
    this app has neither the page blueprint nor a mailer. The link comes from
    `url_for`, or from `deployment_url` once WP-0k lands; whichever name the
    module has is patched.'''
    for module in ('dashboard_api_models', 'permission_api_models'):
        for name in ('url_for', 'deployment_url'):
            monkeypatch.setattr(
                f'web.server.api.{module}.{name}',
                lambda *args, **kwargs: 'http://dashboard.invalid/',
                raising=False,
            )
    monkeypatch.setattr(app, 'email_renderer', mock.Mock(), raising=False)
    monkeypatch.setattr(app, 'notification_service', mock.Mock(), raising=False)


def _in_order(order: str, named, look_alike) -> None:
    '''Calls the two factories so the look-alike is stored first or second.'''
    if order == 'look_alike_first':
        look_alike()
        named()
    else:
        named()
        look_alike()


def _dashboard(db, name: str) -> int:
    resource = Resource(
        resource_type_id=ResourceTypeEnum.DASHBOARD.value, name=name, label=name
    )
    db.session.add(resource)
    db.session.commit()
    return resource.id


def _resource_role_id(db, name: str) -> int:
    return db.session.query(ResourceRole).filter_by(name=name).one().id


def _grant_user(db, user_id: int, role_name: str, resource_id: int) -> None:
    db.session.add(
        UserAcl(
            user_id=user_id,
            resource_role_id=_resource_role_id(db, role_name),
            resource_id=resource_id,
        )
    )
    db.session.commit()


def _group(db, name: str, users=()) -> int:
    group = Group(
        name=name,
        users=db.session.query(User).filter(User.id.in_([u.id for u in users])).all(),
    )
    db.session.add(group)
    db.session.commit()
    return group.id


def _grant_group(db, group_id: int, role_name: str, resource_id: int) -> None:
    db.session.add(
        GroupAcl(
            group_id=group_id,
            resource_role_id=_resource_role_id(db, role_name),
            resource_id=resource_id,
        )
    )
    db.session.commit()


def _holders(db, resource_id: int) -> dict:
    '''Who holds which resource roles on the resource, by user and group name.'''
    db.session.expire_all()
    holders: dict = {}
    for acl in db.session.query(UserAcl).filter_by(resource_id=resource_id):
        holders.setdefault(acl.user.username, []).append(acl.resource_role.name)
    for acl in db.session.query(GroupAcl).filter_by(resource_id=resource_id):
        holders.setdefault(f'group:{acl.group.name}', []).append(acl.resource_role.name)
    return {name: sorted(roles) for name, roles in holders.items()}


def _member_names(db, group_id: int) -> list:
    db.session.expire_all()
    return sorted(user.username for user in db.session.query(Group).get(group_id).users)


def _role_holder_names(db, role_id: int) -> list:
    db.session.expire_all()
    return sorted(
        user.username
        for user in db.session.query(User).all()
        if any(role.id == role_id for role in user.roles)
    )


def _share_body(user_roles: dict, group_roles: dict) -> dict:
    return {
        'userRoles': user_roles,
        'groupRoles': group_roles,
        'sitewideResourceAcl': {
            'registeredResourceRole': '',
            'unregisteredResourceRole': '',
        },
    }


def _account(make_user, local_part: str, tag: str, **kwargs):
    return make_user(username=f'{local_part}-{tag}@escalation.test', **kwargs)


# Path A: a dashboard's own name is looked up again as a pattern.


def test_creating_a_dashboard_makes_its_author_admin_of_that_dashboard_only(
    db, make_user, no_mail, tag
):
    '''Before: the author became dashboard_admin of the look-alike `axb_<tag>`,
    on which it held nothing, and of its own new dashboard not at all.'''
    del no_mail
    look_alike_id = _dashboard(db, f'axb_{tag}')
    author = make_user(['dashboard_creator'])

    response = author.request(
        'POST',
        '/api2/dashboard',
        {'slug': f'a b {tag}', 'specification': _EMPTY_SPECIFICATION},
    )

    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    created_id = int(response.get_json()['resource'].rsplit('/', 1)[1])
    assert {
        'created': _holders(db, created_id),
        'look-alike': _holders(db, look_alike_id),
    } == {'created': {author.username: ['dashboard_admin']}, 'look-alike': {}}


@pytest.mark.parametrize('order', ORDERS)
def test_sharing_a_dashboard_stores_every_acl_on_that_dashboard(
    db, make_user, no_mail, tag, order
):
    '''Before, look-alike first: the author's re-sent dashboard_admin and the
    new viewer's dashboard_viewer were stored on `axb_<tag>`, which the author
    cannot share, and the author lost dashboard_admin on `a_b_<tag>`.'''
    del no_mail
    ids = {}
    _in_order(
        order,
        lambda: ids.update(named=_dashboard(db, f'a_b_{tag}')),
        lambda: ids.update(look_alike=_dashboard(db, f'axb_{tag}')),
    )
    author = make_user()
    viewer = make_user()
    _grant_user(db, author.id, 'dashboard_admin', ids['named'])

    response = author.request(
        'POST',
        f'/api2/resource/{ids["named"]}/roles',
        _share_body(
            {
                author.username: ['dashboard_admin'],
                viewer.username: ['dashboard_viewer'],
            },
            {},
        ),
    )

    assert response.status_code == 204, response.get_data(as_text=True)[:500]
    assert {
        'named': _holders(db, ids['named']),
        'look-alike': _holders(db, ids['look_alike']),
    } == {
        'named': {
            author.username: ['dashboard_admin'],
            viewer.username: ['dashboard_viewer'],
        },
        'look-alike': {},
    }


# Path B: a share is removed by user or group name, matched as a pattern.


@pytest.mark.parametrize('order', ORDERS)
def test_removing_a_users_share_keeps_a_look_alike_users_share(
    db, make_user, no_mail, tag, order
):
    '''Before, look-alike first: `john.doe` lost dashboard_viewer and
    `john_doe`, whose share was removed, kept it.'''
    del no_mail
    dashboard_id = _dashboard(db, f'shared-{tag}')
    author = make_user()
    _grant_user(db, author.id, 'dashboard_admin', dashboard_id)
    users = {}
    _in_order(
        order,
        lambda: users.update(named=_account(make_user, 'john_doe', tag)),
        lambda: users.update(look_alike=_account(make_user, 'john.doe', tag)),
    )
    for user in users.values():
        _grant_user(db, user.id, 'dashboard_viewer', dashboard_id)

    response = author.request(
        'POST',
        f'/api2/resource/{dashboard_id}/roles',
        _share_body(
            {
                author.username: ['dashboard_admin'],
                users['look_alike'].username: ['dashboard_viewer'],
            },
            {},
        ),
    )

    assert response.status_code == 204, response.get_data(as_text=True)[:500]
    assert _holders(db, dashboard_id) == {
        author.username: ['dashboard_admin'],
        users['look_alike'].username: ['dashboard_viewer'],
    }


# `%` matches any run of characters, `_` any one.
GROUP_NAMES = {'underscore': ('team_a', 'teamxa'), 'percent': ('team%a', 'team-q-a')}


@pytest.mark.parametrize('wildcard', sorted(GROUP_NAMES))
@pytest.mark.parametrize('order', ORDERS)
def test_removing_a_groups_share_keeps_a_look_alike_groups_share(
    db, make_user, no_mail, tag, order, wildcard
):
    '''Before, look-alike first: the look-alike group lost dashboard_viewer
    and the named group, whose share was removed, kept it.'''
    del no_mail
    named_name, look_alike_name = (f'{n}-{tag}' for n in GROUP_NAMES[wildcard])
    dashboard_id = _dashboard(db, f'shared-{tag}')
    author = make_user()
    _grant_user(db, author.id, 'dashboard_admin', dashboard_id)
    _in_order(
        order,
        lambda: _group(db, named_name),
        lambda: _group(db, look_alike_name),
    )
    for name in (named_name, look_alike_name):
        group_id = db.session.query(Group).filter_by(name=name).one().id
        _grant_group(db, group_id, 'dashboard_viewer', dashboard_id)

    response = author.request(
        'POST',
        f'/api2/resource/{dashboard_id}/roles',
        _share_body(
            {author.username: ['dashboard_admin']},
            {look_alike_name: ['dashboard_viewer']},
        ),
    )

    assert response.status_code == 204, response.get_data(as_text=True)[:500]
    assert _holders(db, dashboard_id) == {
        author.username: ['dashboard_admin'],
        f'group:{look_alike_name}': ['dashboard_viewer'],
    }


@pytest.mark.parametrize('order', ORDERS)
def test_removing_every_group_share_leaves_no_group_holding_the_dashboard(
    db, make_user, no_mail, tag, order
):
    '''An empty `groupRoles` removes each existing group by name (resource.py
    `_update_group_roles`). Before, look-alike first: `team_a` kept its share.'''
    del no_mail
    dashboard_id = _dashboard(db, f'shared-{tag}')
    author = make_user()
    _grant_user(db, author.id, 'dashboard_admin', dashboard_id)
    _in_order(
        order,
        lambda: _group(db, f'team_a-{tag}'),
        lambda: _group(db, f'teamxa-{tag}'),
    )
    for name in (f'team_a-{tag}', f'teamxa-{tag}'):
        group_id = db.session.query(Group).filter_by(name=name).one().id
        _grant_group(db, group_id, 'dashboard_viewer', dashboard_id)

    response = author.request(
        'POST',
        f'/api2/resource/{dashboard_id}/roles',
        _share_body({author.username: ['dashboard_admin']}, {}),
    )

    assert response.status_code == 204, response.get_data(as_text=True)[:500]
    assert _holders(db, dashboard_id) == {author.username: ['dashboard_admin']}


# Path D: group and role membership by username, matched as a pattern.


def _look_alikes(make_user, tag: str, order: str) -> dict:
    users = {}
    _in_order(
        order,
        lambda: users.update(named=_account(make_user, 'john_doe', tag)),
        lambda: users.update(look_alike=_account(make_user, 'john.doe', tag)),
    )
    return users


@pytest.mark.parametrize('order', ORDERS)
def test_adding_a_user_to_a_group_by_username_adds_that_user(db, make_user, tag, order):
    '''Before, look-alike first: `john.doe` joined the group.'''
    admin = make_user(['admin'])
    users = _look_alikes(make_user, tag, order)
    group_id = _group(db, f'members-{tag}')

    response = admin.request(
        'POST', f'/api2/group/{group_id}/users', users['named'].username
    )

    assert response.status_code in (200, 201), response.get_data(as_text=True)[:500]
    assert _member_names(db, group_id) == [users['named'].username]


@pytest.mark.parametrize('order', ORDERS)
def test_setting_a_groups_members_by_username_adds_those_users(
    db, make_user, tag, order
):
    '''Before, look-alike first: `john.doe` joined the group.'''
    admin = make_user(['admin'])
    users = _look_alikes(make_user, tag, order)
    group_id = _group(db, f'members-{tag}')

    response = admin.request(
        'PATCH', f'/api2/group/{group_id}/users', [users['named'].username]
    )

    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    assert _member_names(db, group_id) == [users['named'].username]


@pytest.mark.parametrize('order', ORDERS)
def test_deleting_a_user_from_a_group_by_username_removes_that_user(
    db, make_user, tag, order
):
    '''Before, look-alike first: `john.doe` left the group and `john_doe`
    stayed in it.'''
    admin = make_user(['admin'])
    users = _look_alikes(make_user, tag, order)
    group_id = _group(db, f'members-{tag}', users=users.values())

    response = admin.request(
        'DELETE', f'/api2/group/{group_id}/users', users['named'].username
    )

    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    assert _member_names(db, group_id) == [users['look_alike'].username]


@pytest.mark.parametrize('order', ORDERS)
def test_setting_a_roles_users_by_username_adds_those_users(db, make_user, tag, order):
    '''Before, look-alike first: `john.doe` received the role.'''
    admin = make_user(['admin'])
    users = _look_alikes(make_user, tag, order)
    role = Role(name=f'members-{tag}', label=f'members-{tag}')
    db.session.add(role)
    db.session.commit()
    role_id = role.id

    response = admin.request(
        'PATCH', f'/api2/role/{role_id}/users', [users['named'].username]
    )

    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    assert _role_holder_names(db, role_id) == [users['named'].username]


@pytest.mark.parametrize('route', ['group POST', 'group PATCH', 'role PATCH'])
def test_a_username_only_a_look_alike_matches_is_not_found(db, make_user, tag, route):
    '''INV-3 (decision 0012): a name with `_` and no exact match is a 404.
    Before: the look-alike `john.doe` joined the group or received the role.'''
    admin = make_user(['admin'])
    look_alike = _account(make_user, 'john.doe', tag)
    username = f'john_doe-{tag}@escalation.test'
    group_id = _group(db, f'members-{tag}')
    role = Role(name=f'members-{tag}', label=f'members-{tag}')
    db.session.add(role)
    db.session.commit()
    role_id = role.id
    method, url, body = {
        'group POST': ('POST', f'/api2/group/{group_id}/users', username),
        'group PATCH': ('PATCH', f'/api2/group/{group_id}/users', [username]),
        'role PATCH': ('PATCH', f'/api2/role/{role_id}/users', [username]),
    }[route]

    response = admin.request(method, url, body)

    assert response.status_code == 404, response.get_data(as_text=True)[:500]
    assert look_alike.username not in _member_names(db, group_id)
    assert look_alike.username not in _role_holder_names(db, role_id)


def test_group_membership_by_username_still_ignores_case(db, make_user, tag):
    '''Unchanged by WP-0l: a username matches whatever its case.'''
    admin = make_user(['admin'])
    member = _account(make_user, 'plain', tag)
    group_id = _group(db, f'members-{tag}')

    response = admin.request(
        'POST', f'/api2/group/{group_id}/users', member.username.upper()
    )

    assert response.status_code in (200, 201), response.get_data(as_text=True)[:500]
    assert _member_names(db, group_id) == [member.username]


# Unchanged by WP-0l: group, dashboard and resource role names match whatever
# their case, as usernames do.


def test_a_share_names_a_group_whatever_its_case(db, make_user, no_mail, tag):
    del no_mail
    dashboard_id = _dashboard(db, f'shared-{tag}')
    author = make_user()
    _grant_user(db, author.id, 'dashboard_admin', dashboard_id)
    group_name = f'Team-{tag}'
    _group(db, group_name)

    response = author.request(
        'POST',
        f'/api2/resource/{dashboard_id}/roles',
        _share_body(
            {author.username: ['dashboard_admin']},
            {group_name.upper(): ['dashboard_viewer']},
        ),
    )

    assert response.status_code == 204, response.get_data(as_text=True)[:500]
    assert _holders(db, dashboard_id) == {
        author.username: ['dashboard_admin'],
        f'group:{group_name}': ['dashboard_viewer'],
    }


def test_a_share_names_a_resource_role_whatever_its_case(db, make_user, no_mail, tag):
    del no_mail
    dashboard_id = _dashboard(db, f'shared-{tag}')
    author = make_user()
    viewer = make_user()
    _grant_user(db, author.id, 'dashboard_admin', dashboard_id)

    response = author.request(
        'POST',
        f'/api2/resource/{dashboard_id}/roles',
        _share_body(
            {
                author.username: ['dashboard_admin'],
                viewer.username: ['DASHBOARD_VIEWER'],
            },
            {},
        ),
    )

    assert response.status_code == 204, response.get_data(as_text=True)[:500]
    assert _holders(db, dashboard_id) == {
        author.username: ['dashboard_admin'],
        viewer.username: ['dashboard_viewer'],
    }


@pytest.mark.parametrize('upper', ['dashboard', 'resource role'])
def test_an_acl_names_a_dashboard_and_resource_role_whatever_their_case(
    db, make_user, tag, upper
):
    admin = make_user(['admin'])
    group_name = f'grants-{tag}'
    group_id = _group(db, group_name)
    dashboard_name = f'mixed-{tag}'
    dashboard_id = _dashboard(db, dashboard_name)
    body = _group_acl_body(
        group_name,
        [],
        dashboard_name.upper() if upper == 'dashboard' else dashboard_name,
        'DASHBOARD_VIEWER' if upper == 'resource role' else 'dashboard_viewer',
    )

    response = admin.request('PATCH', f'/api2/group/{group_id}', body)

    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    assert _holders(db, dashboard_id) == {f'group:{group_name}': ['dashboard_viewer']}


# Path C: the 403 for an ACL grant repeated the matched dashboard's real name.


def _group_acl_body(
    group_name: str, users, resource_name: str, role_name: str = 'dashboard_viewer'
) -> dict:
    return {
        '$uri': '',
        'name': group_name,
        'roles': [],
        'users': [u.username for u in users],
        'acls': [
            {
                '$uri': '',
                'resourceRole': {
                    '$uri': '',
                    'name': role_name,
                    'resourceType': 'DASHBOARD',
                },
                'resource': {
                    '$uri': '',
                    'label': resource_name,
                    'name': resource_name,
                    'resourceType': 'DASHBOARD',
                },
            }
        ],
    }


def test_a_refused_acl_grant_does_not_name_the_dashboard(db, make_user, tag):
    '''Before: 403 "Granting 'dashboard_viewer' on DASHBOARD '<name>' needs
    ...". After: 403 that names no dashboard. The actor can view the
    dashboard but not share it: since WP-0l a dashboard the caller cannot
    see is a 404, the same as one that does not exist (INV-3 row 7).'''
    actor = make_user(['group_moderator'])
    group_name = f'grants-{tag}'
    group_id = _group(db, group_name, users=[actor])
    dashboard_name = f'private-{tag}'
    _grant_user(db, actor.id, 'dashboard_viewer', _dashboard(db, dashboard_name))

    response = actor.request(
        'PATCH',
        f'/api2/group/{group_id}',
        _group_acl_body(group_name, [actor], dashboard_name),
    )

    assert response.status_code == 403
    assert dashboard_name not in response.get_data(as_text=True)
    assert db.session.query(Group).get(group_id).acls == []


def test_an_acl_naming_a_pattern_does_not_reveal_the_dashboard_it_matches(
    db, make_user, tag
):
    '''Before: `a_b_<tag>` matched `axb_<tag>`, which the caller cannot list,
    and the 403 named `axb_<tag>`. After: no dashboard is named `a_b_<tag>`,
    so the grant is refused or not found, and the body names neither.'''
    actor = make_user(['group_moderator'])
    group_name = f'grants-{tag}'
    group_id = _group(db, group_name, users=[actor])
    hidden_name = f'axb_{tag}'
    _dashboard(db, hidden_name)

    response = actor.request(
        'PATCH',
        f'/api2/group/{group_id}',
        _group_acl_body(group_name, [actor], f'a_b_{tag}'),
    )

    assert response.status_code in (403, 404)
    assert hidden_name not in response.get_data(as_text=True)
    assert db.session.query(Group).get(group_id).acls == []
