'''WP-0l (decision 0012): resources, groups and users named in a request are
found by exact name, ignoring case, never as a LIKE pattern, and a resource the
code already holds is never looked up again by its name.

Names here pair a target with a look-alike that the target's name matches as
a pattern (`_` matches any one character), created first so an unordered
`first()` returns it.
'''

from __future__ import annotations

import uuid

import pytest

from models.alchemy.alerts import AlertDefinition
from models.alchemy.dashboard import Dashboard
from models.alchemy.permission import (
    Permission,
    Resource,
    ResourceRole,
    ResourceTypeEnum,
    Role,
)
from models.alchemy.security_group import Group, GroupAcl
from models.alchemy.user import User, UserAcl, UserRoles, UserStatusEnum
from web.server.errors import ItemNotFound

_PASSWORD = 'escalation-test-password'
_NO_SITEWIDE_ACL = {'registeredResourceRole': '', 'unregisteredResourceRole': ''}


@pytest.fixture(name='db')
def fixture_db(app):
    with app.app_context():
        yield app.extensions['sqlalchemy'].db


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def _resource(db, name: str, resource_type: str = 'DASHBOARD') -> Resource:
    resource = Resource(
        resource_type_id=ResourceTypeEnum[resource_type].value, name=name, label=name
    )
    db.session.add(resource)
    db.session.commit()
    return resource


def _account(app, db, username: str) -> int:
    user = User(
        username=username,
        password=app.user_manager.hash_password(_PASSWORD),
        first_name='Named',
        last_name='Lookup',
        status_id=UserStatusEnum.ACTIVE.value,
    )
    db.session.add(user)
    db.session.commit()
    return user.id


def _group(db, name: str) -> Group:
    group = Group(name=name)
    db.session.add(group)
    db.session.commit()
    return group


def _resource_role(db, name: str) -> ResourceRole:
    return db.session.query(ResourceRole).filter_by(name=name).one()


def _grant_user(db, user_id: int, role_name: str, resource_id: int) -> None:
    db.session.add(
        UserAcl(
            user_id=user_id,
            resource_role_id=_resource_role(db, role_name).id,
            resource_id=resource_id,
        )
    )
    db.session.commit()


def _grant_group(db, group_id: int, role_name: str, resource_id: int) -> None:
    db.session.add(
        GroupAcl(
            group_id=group_id,
            resource_role_id=_resource_role(db, role_name).id,
            resource_id=resource_id,
        )
    )
    db.session.commit()


def _user_acls(db, resource_id: int) -> set:
    db.session.expire_all()
    return {
        (acl.user_id, acl.resource_role.name)
        for acl in db.session.query(UserAcl).filter_by(resource_id=resource_id)
    }


def _group_acls(db, resource_id: int) -> set:
    db.session.expire_all()
    return {
        (acl.group_id, acl.resource_role.name)
        for acl in db.session.query(GroupAcl).filter_by(resource_id=resource_id)
    }


def _share(actor, resource_id: int, user_roles=None, group_roles=None):
    return actor.request(
        'POST',
        f'/api2/resource/{resource_id}/roles',
        {
            'userRoles': user_roles or {},
            'groupRoles': group_roles or {},
            'sitewideResourceAcl': _NO_SITEWIDE_ACL,
        },
    )


# Unit 2: sharing and author grants use the resource they were given.


def test_sharing_a_dashboard_stores_its_acls_on_that_dashboard(db, make_user):
    tag = _tag()
    look_alike_id = _resource(db, f'{tag}x{tag}').id
    target_id = _resource(db, f'{tag}_{tag}').id
    actor = make_user()
    other = make_user()
    _grant_user(db, actor.id, 'dashboard_admin', target_id)
    _grant_user(db, other.id, 'dashboard_viewer', target_id)

    response = _share(
        actor,
        target_id,
        {
            actor.username: ['dashboard_admin'],
            other.username: ['dashboard_admin'],
        },
    )

    assert response.status_code == 204
    assert _user_acls(db, target_id) == {
        (actor.id, 'dashboard_admin'),
        (other.id, 'dashboard_admin'),
    }
    assert _user_acls(db, look_alike_id) == set()


def test_sharing_a_dashboard_with_a_group_stores_its_acl_on_that_dashboard(
    db, make_user
):
    tag = _tag()
    look_alike_id = _resource(db, f'{tag}x{tag}').id
    target_id = _resource(db, f'{tag}_{tag}').id
    actor = make_user()
    _grant_user(db, actor.id, 'dashboard_admin', target_id)
    group = _group(db, f'group-{tag}')
    group_id, group_name = group.id, group.name

    response = _share(
        actor,
        target_id,
        {actor.username: ['dashboard_admin']},
        {group_name: ['dashboard_viewer']},
    )

    assert response.status_code == 204
    assert _group_acls(db, target_id) == {(group_id, 'dashboard_viewer')}
    assert _group_acls(db, look_alike_id) == set()


def test_creating_a_dashboard_makes_its_author_admin_of_that_dashboard(db, make_user):
    tag = _tag()
    look_alike_id = _resource(db, f'{tag}x{tag}').id
    creator_role = Role(
        name=f'creator-{tag}',
        label='creator',
        permissions=[
            db.session.query(Permission)
            .filter_by(
                resource_type_id=ResourceTypeEnum.DASHBOARD.value,
                permission='create_resource',
            )
            .one()
        ],
    )
    db.session.add(creator_role)
    db.session.commit()
    actor = make_user([creator_role.name])

    actor.request(
        'POST',
        '/api2/dashboard',
        {'slug': f'{tag}_{tag}', 'specification': {'options': {'title': tag}}},
    )

    db.session.expire_all()
    dashboard = db.session.query(Dashboard).filter_by(slug=f'{tag}_{tag}').one()
    assert _user_acls(db, dashboard.resource_id) == {(actor.id, 'dashboard_admin')}
    assert _user_acls(db, look_alike_id) == set()


# Share removal acts on the exact principal holding the share.


def test_a_share_naming_a_holder_in_another_case_keeps_its_roles(db, make_user):
    dashboard_id = _resource(db, f'dashboard-{_tag()}').id
    actor = make_user()
    other = make_user()
    _grant_user(db, actor.id, 'dashboard_admin', dashboard_id)
    _grant_user(db, other.id, 'dashboard_viewer', dashboard_id)

    response = _share(
        actor,
        dashboard_id,
        {
            actor.username: ['dashboard_admin'],
            other.username.upper(): ['dashboard_viewer'],
        },
    )

    assert response.status_code == 204
    assert _user_acls(db, dashboard_id) == {
        (actor.id, 'dashboard_admin'),
        (other.id, 'dashboard_viewer'),
    }


def test_removing_a_users_share_removes_only_that_users_acls(app, db, make_user):
    tag = _tag()
    dashboard_id = _resource(db, f'dashboard-{tag}').id
    actor = make_user()
    look_alike_id = _account(app, db, f'{tag}.doe@named.test')
    target_id = _account(app, db, f'{tag}_doe@named.test')
    _grant_user(db, actor.id, 'dashboard_admin', dashboard_id)
    _grant_user(db, look_alike_id, 'dashboard_viewer', dashboard_id)
    _grant_user(db, target_id, 'dashboard_viewer', dashboard_id)

    response = _share(
        actor,
        dashboard_id,
        {
            actor.username: ['dashboard_admin'],
            f'{tag}.doe@named.test': ['dashboard_viewer'],
        },
    )

    assert response.status_code == 204
    assert _user_acls(db, dashboard_id) == {
        (actor.id, 'dashboard_admin'),
        (look_alike_id, 'dashboard_viewer'),
    }


def test_a_share_naming_an_unknown_user_writes_nothing(db, make_user):
    dashboard_id = _resource(db, f'dashboard-{_tag()}').id
    actor = make_user()
    _grant_user(db, actor.id, 'dashboard_admin', dashboard_id)
    group = _group(db, f'group-{_tag()}')
    group_id = group.id
    _grant_group(db, group_id, 'dashboard_viewer', dashboard_id)

    response = _share(
        actor,
        dashboard_id,
        {
            actor.username: ['dashboard_admin'],
            f'nobody-{_tag()}@named.test': ['dashboard_viewer'],
        },
        {},
    )

    assert response.status_code == 404
    assert _user_acls(db, dashboard_id) == {(actor.id, 'dashboard_admin')}
    assert _group_acls(db, dashboard_id) == {(group_id, 'dashboard_viewer')}


# Unit 3: refusals do not repeat the names of resources the caller cannot list.


def test_a_refused_acl_grant_does_not_name_the_resource(db, make_user):
    actor = make_user(['group_moderator'])
    group = Group(name=f'group-{_tag()}', users=[db.session.query(User).get(actor.id)])
    db.session.add(group)
    db.session.commit()
    group_id, group_name = group.id, group.name
    dashboard_name = f'secret-{_tag()}'
    _resource(db, dashboard_name)

    response = actor.request(
        'PATCH',
        f'/api2/group/{group_id}',
        {
            '$uri': '',
            'name': group_name,
            'roles': [],
            'users': [actor.username],
            'acls': [_acl('dashboard_admin', dashboard_name)],
        },
    )

    assert response.status_code == 403
    assert dashboard_name not in response.get_data(as_text=True)


def test_a_resource_role_of_another_type_does_not_name_the_resource(app, db, make_user):
    admin = make_user(['admin'])
    target_id = _account(app, db, f'target-{_tag()}@named.test')
    dashboard_name = f'secret-{_tag()}'
    _resource(db, dashboard_name)
    db.session.expire_all()
    target = db.session.query(User).get(target_id)

    response = admin.request(
        'PATCH',
        f'/api2/user/{target_id}',
        {
            '$uri': f'/api2/user/{target_id}',
            'username': target.username,
            'firstName': target.first_name,
            'lastName': target.last_name,
            'phoneNumber': '',
            'status': 'active',
            'acls': [_acl('alert_admin', dashboard_name)],
            'apiTokens': [],
            'roles': [],
            'groups': [],
        },
    )

    assert response.status_code == 404
    assert dashboard_name not in response.get_data(as_text=True)


def _acl(resource_role_name: str, resource_name: str) -> dict:
    return {
        '$uri': '',
        'resourceRole': {
            '$uri': '',
            'name': resource_role_name,
            'resourceType': 'DASHBOARD',
        },
        'resource': {
            '$uri': '',
            'label': resource_name,
            'name': resource_name,
            'resourceType': 'DASHBOARD',
        },
    }


# Unit 4: users named by username match exactly, ignoring case.


def _role_with_no_users(db) -> Role:
    role = Role(name=f'members-{_tag()}', label='members')
    db.session.add(role)
    db.session.commit()
    return role


def _role_user_ids(db, role_id: int) -> set:
    db.session.expire_all()
    return {
        row.user_id for row in db.session.query(UserRoles).filter_by(role_id=role_id)
    }


def test_role_membership_by_a_look_alike_username_adds_nobody(app, db, make_user):
    admin = make_user(['admin'])
    tag = _tag()
    _account(app, db, f'{tag}.doe@named.test')
    role_id = _role_with_no_users(db).id

    response = admin.request(
        'PATCH', f'/api2/role/{role_id}/users', [f'{tag}_doe@named.test']
    )

    assert response.status_code == 404
    assert _role_user_ids(db, role_id) == set()


def test_role_membership_by_username_ignores_case(app, db, make_user):
    admin = make_user(['admin'])
    user_id = _account(app, db, f'{_tag()}.doe@named.test')
    db.session.expire_all()
    username = db.session.query(User).get(user_id).username
    role_id = _role_with_no_users(db).id

    response = admin.request('PATCH', f'/api2/role/{role_id}/users', [username.upper()])

    assert response.status_code == 200
    assert _role_user_ids(db, role_id) == {user_id}


def _dashboard_by(db, author_id: int) -> int:
    resource = _resource(db, f'dashboard-{_tag()}')
    dashboard = Dashboard(
        slug=resource.name,
        specification={'options': {'title': resource.name}},
        resource_id=resource.id,
        author_id=author_id,
    )
    db.session.add(dashboard)
    db.session.commit()
    return dashboard.id


def _author_of(db, dashboard_id: int) -> int:
    db.session.expire_all()
    return db.session.query(Dashboard).get(dashboard_id).author_id


def test_dashboard_transfer_from_a_look_alike_username_moves_nothing(
    app, db, make_user
):
    admin = make_user(['admin'])
    tag = _tag()
    look_alike_id = _account(app, db, f'{tag}.doe@named.test')
    dashboard_id = _dashboard_by(db, look_alike_id)

    response = admin.request(
        'POST',
        '/api2/dashboard/transfer/username',
        {'sourceAuthor': f'{tag}_doe@named.test', 'targetAuthor': admin.username},
    )

    assert response.status_code == 404
    assert _author_of(db, dashboard_id) == look_alike_id


def test_dashboard_transfer_by_username_ignores_case(app, db, make_user):
    admin = make_user(['admin'])
    source_id = _account(app, db, f'{_tag()}.doe@named.test')
    dashboard_id = _dashboard_by(db, source_id)
    db.session.expire_all()
    source_username = db.session.query(User).get(source_id).username

    response = admin.request(
        'POST',
        '/api2/dashboard/transfer/username',
        {
            'sourceAuthor': source_username.upper(),
            'targetAuthor': admin.username.upper(),
        },
    )

    assert response.status_code == 204
    assert _author_of(db, dashboard_id) == admin.id


@pytest.mark.parametrize('side', ['sourceUser', 'targetUser'])
def test_alert_transfer_naming_no_user_is_not_found(app, db, make_user, side):
    admin = make_user(['admin'])
    tag = _tag()
    _account(app, db, f'{tag}.doe@named.test')
    body = {'sourceUser': admin.username, 'targetUser': admin.username}
    body[side] = f'{tag}_doe@named.test'

    response = admin.request('POST', '/api2/alert_definitions/transfer/username', body)

    assert response.status_code == 404


def test_alert_transfer_by_username_ignores_case(app, db, make_user):
    admin = make_user(['admin'])
    source_id = _account(app, db, f'{_tag()}.doe@named.test')
    resource = _resource(db, f'alert-{_tag()}', 'ALERT')
    alert = AlertDefinition(
        checks=[],
        dimension_name=None,
        filters=[],
        fields=[],
        time_granularity='month',
        title='alert',
        user_id=source_id,
        authorization_resource_id=resource.id,
    )
    db.session.add(alert)
    db.session.commit()
    alert_id, resource_id = alert.id, resource.id
    db.session.expire_all()
    source_username = db.session.query(User).get(source_id).username

    response = admin.request(
        'POST',
        '/api2/alert_definitions/transfer/username',
        {'sourceUser': source_username.upper(), 'targetUser': admin.username},
    )

    assert response.status_code == 204
    db.session.expire_all()
    assert db.session.query(AlertDefinition).get(alert_id).user_id == admin.id
    assert (admin.id, 'alert_admin') in _user_acls(db, resource_id)


# Names unique only as stored: a name equal to several rows ignoring case
# finds the row spelled exactly that way, else nobody.


def test_a_group_named_in_another_case_than_two_groups_is_not_found(db, make_user):
    tag = _tag()
    dashboard_id = _resource(db, f'dashboard-{tag}').id
    actor = make_user()
    _grant_user(db, actor.id, 'dashboard_admin', dashboard_id)
    upper_id = _group(db, f'Pair-{tag}').id
    lower_id = _group(db, f'pair-{tag}').id

    ambiguous = _share(
        actor,
        dashboard_id,
        {actor.username: ['dashboard_admin']},
        {f'PAIR-{tag}': ['dashboard_viewer']},
    )
    exact = _share(
        actor,
        dashboard_id,
        {actor.username: ['dashboard_admin']},
        {f'pair-{tag}': ['dashboard_viewer']},
    )

    assert ambiguous.status_code == 404
    assert exact.status_code == 204
    assert _group_acls(db, dashboard_id) == {(lower_id, 'dashboard_viewer')}
    assert upper_id != lower_id


def test_a_user_named_in_another_case_than_two_accounts_is_not_found(
    app, db, make_user
):
    admin = make_user(['admin'])
    tag = _tag()
    _account(app, db, f'Pair-{tag}@named.test')
    lower_id = _account(app, db, f'pair-{tag}@named.test')
    role_id = _role_with_no_users(db).id

    ambiguous = admin.request(
        'PATCH', f'/api2/role/{role_id}/users', [f'PAIR-{tag}@named.test']
    )
    exact = admin.request(
        'PATCH', f'/api2/role/{role_id}/users', [f'pair-{tag}@named.test']
    )

    assert ambiguous.status_code == 404
    assert exact.status_code == 200
    assert _role_user_ids(db, role_id) == {lower_id}


def test_an_acl_naming_a_resource_two_resources_share_is_not_found(app, db, make_user):
    admin = make_user(['admin'])
    target_id = _account(app, db, f'target-{_tag()}@named.test')
    shared_name = f'twin-{_tag()}'
    _resource(db, shared_name)
    _resource(db, shared_name)
    db.session.expire_all()
    target = db.session.query(User).get(target_id)

    response = admin.request(
        'PATCH',
        f'/api2/user/{target_id}',
        {
            '$uri': f'/api2/user/{target_id}',
            'username': target.username,
            'firstName': target.first_name,
            'lastName': target.last_name,
            'phoneNumber': '',
            'status': 'active',
            'acls': [_acl('dashboard_viewer', shared_name)],
            'apiTokens': [],
            'roles': [],
            'groups': [],
        },
    )

    assert response.status_code == 404
    db.session.expire_all()
    assert db.session.query(User).get(target_id).acls == []


# Unit 5: the tracing notes in decision 0012.


def test_a_resource_is_found_by_type_and_name_not_by_name_alone(app, db):
    # pylint: disable=import-outside-toplevel
    from web.server.routes.views.resource import get_resource_by_type_and_name

    name = f'alert_{_tag()}'
    alert_id = _resource(db, name, 'ALERT').id

    with app.test_request_context():
        assert get_resource_by_type_and_name('alert', name).id == alert_id
        with pytest.raises(ItemNotFound):
            get_resource_by_type_and_name('dashboard', name)


@pytest.mark.parametrize('target', ['user', 'group'])
def test_the_legacy_single_role_post_is_refused_cleanly(app, db, make_user, target):
    admin = make_user(['admin'])
    if target == 'user':
        target_id = _account(app, db, f'target-{_tag()}@named.test')
    else:
        target_id = _group(db, f'group-{_tag()}').id

    response = admin.request(
        'POST',
        f'/api2/{target}/{target_id}/roles',
        {'roleName': 'dashboard_viewer', 'resourceType': 'DASHBOARD'},
    )

    assert response.status_code == 400
    db.session.expire_all()
    model = User if target == 'user' else Group
    assert db.session.query(model).get(target_id).roles == []


@pytest.mark.parametrize('target', ['user', 'group'])
def test_a_non_empty_legacy_role_map_is_refused_and_keeps_the_roles(
    app, db, make_user, target
):
    admin = make_user(['admin'])
    held = db.session.query(Role).filter_by(name='manager').one()
    if target == 'user':
        target_id = _account(app, db, f'target-{_tag()}@named.test')
        db.session.query(User).get(target_id).roles = [held]
    else:
        group = Group(name=f'group-{_tag()}', roles=[held])
        db.session.add(group)
        db.session.flush()
        target_id = group.id
    db.session.commit()

    response = admin.request(
        'PATCH',
        f'/api2/{target}/{target_id}/roles',
        {'SITE': {'sitewideRoles': ['dashboard_viewer'], 'resources': {}}},
    )

    assert response.status_code == 400
    db.session.expire_all()
    model = User if target == 'user' else Group
    assert [role.name for role in db.session.query(model).get(target_id).roles] == [
        'manager'
    ]
