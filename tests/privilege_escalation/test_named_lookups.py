'''WP-0l (decision 0012): resources, groups and users named in a request are
found by exact name, ignoring case, never as a LIKE pattern, and a resource the
code already holds is never looked up again by its name.

Names here pair a target with a look-alike that the target's name matches as
a pattern (`_` matches any one character), created first so an unordered
`first()` returns it.
'''

from __future__ import annotations

import logging
import uuid
from unittest import mock

import pytest

from models.alchemy.alerts import AlertDefinition
from models.alchemy.dashboard import Dashboard
from models.alchemy.permission import (
    Permission,
    Resource,
    ResourceRole,
    ResourceTypeEnum,
    Role,
    SitewideResourceAcl,
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


@pytest.mark.parametrize('unknown', ['user', 'look_alike'])
def test_a_share_naming_no_one_leaves_the_sitewide_acl_alone(
    app, db, make_user, unknown
):
    tag = _tag()
    dashboard_id = _resource(db, f'dashboard-{tag}').id
    actor = make_user()
    _grant_user(db, actor.id, 'dashboard_admin', dashboard_id)
    _account(app, db, f'{tag}.doe@named.test')
    name = f'nobody-{tag}@named.test' if unknown == 'user' else f'{tag}_doe@named.test'

    response = actor.request(
        'POST',
        f'/api2/resource/{dashboard_id}/roles',
        {
            'userRoles': {
                actor.username: ['dashboard_admin'],
                name: ['dashboard_viewer'],
            },
            'groupRoles': {},
            'sitewideResourceAcl': {
                'registeredResourceRole': 'dashboard_viewer',
                'unregisteredResourceRole': '',
            },
        },
    )

    assert response.status_code == 404
    db.session.expire_all()
    assert (
        db.session.query(SitewideResourceAcl).filter_by(resource_id=dashboard_id).all()
        == []
    )


# Unit 3: refusals do not repeat the names of resources the caller cannot list.


def test_a_refused_acl_grant_does_not_name_the_resource(db, make_user):
    actor = make_user(['group_moderator'])
    group = Group(name=f'group-{_tag()}', users=[db.session.query(User).get(actor.id)])
    db.session.add(group)
    db.session.commit()
    group_id, group_name = group.id, group.name
    dashboard_name = f'secret-{_tag()}'
    # Visible but not shareable: one the caller cannot see is a 404 (row 7).
    _grant_user(db, actor.id, 'dashboard_viewer', _resource(db, dashboard_name).id)

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


def test_a_name_two_resources_of_the_type_share_finds_neither(app, db):
    # pylint: disable=import-outside-toplevel
    from web.server.routes.views.resource import get_resource_by_type_and_name

    name = f't{_tag()}_x'
    _resource(db, name)
    _resource(db, name)

    with app.test_request_context():
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


@pytest.mark.parametrize('target', ['user', 'group'])
def test_a_legacy_role_map_naming_no_role_still_removes_every_role(
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
        {'SITE': {'sitewideRoles': [], 'resources': {f'dashboard-{_tag()}': []}}},
    )

    assert response.status_code == 200
    db.session.expire_all()
    model = User if target == 'user' else Group
    assert db.session.query(model).get(target_id).roles == []


def _authorization_request(app, actor, handler_name: str, body):
    '''Runs an `/api/authorization*` handler in a request context: the session
    app has served requests, so the `/api` blueprint cannot be registered on it
    any more.'''
    # pylint: disable=import-outside-toplevel
    from web.server.routes.api import ApiRouter

    with app.test_request_context(
        f'/api/{handler_name}',
        method='POST',
        json=body,
        headers={'X-Username': actor.username, 'X-Password': _PASSWORD},
    ):
        return getattr(ApiRouter(None, None), f'api_is_{handler_name}')()


@pytest.mark.parametrize('handler', ['authorized', 'authorized_multi'])
@pytest.mark.parametrize('resource_type', [None, 7])
def test_an_authorization_check_without_a_resource_type_is_a_json_400(
    app, db, make_user, handler, resource_type
):
    actor = make_user(['admin'])
    name = f'dashboard_{_tag()}'
    _resource(db, name)
    check = {
        'permission': 'view_resource',
        'resourceType': resource_type,
        'resourceName': name,
    }

    response, status = _authorization_request(
        app, actor, handler, check if handler == 'authorized' else [check]
    )

    assert status == 400
    assert response.is_json
    assert response.get_json()['success'] is False


def test_an_authorization_check_naming_an_unknown_type_is_not_found(app, db, make_user):
    actor = make_user(['admin'])
    name = f'dashboard_{_tag()}'
    _resource(db, name)

    with pytest.raises(ItemNotFound):
        _authorization_request(
            app,
            actor,
            'authorized',
            {
                'permission': 'view_resource',
                'resourceType': 'no_such_type',
                'resourceName': name,
            },
        )


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def test_clearing_a_users_roles_logs_the_target_by_username_only(make_user):
    admin = make_user(['admin'])
    target = make_user()
    handler = _Records()
    app_logger = logging.getLogger('ZenysisLogger')
    app_logger.addHandler(handler)
    try:
        response = admin.request('PATCH', f'/api2/user/{target.id}/roles', {})
    finally:
        app_logger.removeHandler(handler)

    assert response.status_code == 200
    assert [line for line in handler.lines if 'every role' in line] == [
        f'Removed every role from user \'{target.username}\'.'
    ]


# Round 2: transferring one dashboard moves that dashboard and nothing else.


def test_transferring_a_dashboard_moves_only_that_dashboard(app, db, make_user):
    owner = make_user()
    new_owner = make_user()
    # A user whose id equals the transferred dashboard's id: the transfer once
    # moved every dashboard that user authored.
    clash_id = 900000 + int(_tag()[:5], 16)
    victim = User(
        id=clash_id,
        username=f'victim-{_tag()}@named.test',
        password=app.user_manager.hash_password(_PASSWORD),
        first_name='Named',
        last_name='Victim',
        status_id=UserStatusEnum.ACTIVE.value,
    )
    db.session.add(victim)
    resource = _resource(db, f'dashboard-{_tag()}')
    resource_id = resource.id
    db.session.add(
        Dashboard(
            id=clash_id,
            slug=resource.name,
            specification={'options': {'title': resource.name}},
            resource_id=resource_id,
            author_id=owner.id,
        )
    )
    db.session.commit()
    _grant_user(db, owner.id, 'dashboard_admin', resource_id)
    victims_dashboard_id = _dashboard_by(db, clash_id)

    response = owner.request(
        'POST',
        f'/api2/dashboard/{resource_id}/transfer/username',
        new_owner.username,
    )

    assert response.status_code == 204
    assert _author_of(db, clash_id) == new_owner.id
    assert _author_of(db, victims_dashboard_id) == clash_id
    assert (new_owner.id, 'dashboard_admin') in _user_acls(db, resource_id)


# Round 2: twins. The slugs `t-x` and `t_x` both slugify to the resource name
# `t_x`, so exact matching alone cannot tell them apart: only acting on the
# resource object the code already holds lands each grant on the right twin.


@pytest.fixture(name='no_mail')
def fixture_no_mail(app, monkeypatch):
    '''Creating or sharing a dashboard mails a link to the dashboard page; this
    app has neither the page blueprint nor a mailer. The link comes from
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


def _twin(db, make_user, slug: str):
    '''A dashboard with `slug`, created through the API by a new creator, who
    is returned with the dashboard's resource id.'''
    creator = make_user(['dashboard_creator'])
    response = creator.request(
        'POST',
        '/api2/dashboard',
        {'slug': slug, 'specification': {'options': {'title': slug}}},
    )
    assert response.status_code in (200, 201)
    db.session.expire_all()
    return creator, db.session.query(Dashboard).filter_by(slug=slug).one().resource_id


def test_creating_a_twin_makes_its_author_admin_of_that_twin(db, make_user, no_mail):
    del no_mail
    tag = _tag()
    first_creator, first_id = _twin(db, make_user, f't{tag}-x')
    second_creator, second_id = _twin(db, make_user, f't{tag}_x')

    assert _user_acls(db, first_id) == {(first_creator.id, 'dashboard_admin')}
    assert _user_acls(db, second_id) == {(second_creator.id, 'dashboard_admin')}


def test_sharing_a_twin_by_id_stores_its_acls_on_that_twin(db, make_user, no_mail):
    del no_mail
    tag = _tag()
    first_creator, first_id = _twin(db, make_user, f't{tag}-x')
    second_creator, second_id = _twin(db, make_user, f't{tag}_x')
    other = make_user()

    response = _share(
        second_creator,
        second_id,
        {
            second_creator.username: ['dashboard_admin'],
            other.username: ['dashboard_viewer'],
        },
    )

    assert response.status_code == 204
    assert _user_acls(db, first_id) == {(first_creator.id, 'dashboard_admin')}
    assert _user_acls(db, second_id) == {
        (second_creator.id, 'dashboard_admin'),
        (other.id, 'dashboard_viewer'),
    }


def test_transferring_a_twin_makes_the_new_owner_admin_of_that_twin(
    db, make_user, no_mail
):
    del no_mail
    tag = _tag()
    first_creator, first_id = _twin(db, make_user, f't{tag}-x')
    second_creator, second_id = _twin(db, make_user, f't{tag}_x')
    new_owner = make_user()

    response = second_creator.request(
        'POST',
        f'/api2/dashboard/{second_id}/transfer/username',
        new_owner.username,
    )

    assert response.status_code == 204
    assert _user_acls(db, first_id) == {(first_creator.id, 'dashboard_admin')}
    assert (new_owner.id, 'dashboard_admin') in _user_acls(db, second_id)


# Round 2: an ACL in a group or user update names its resource by `$uri` when
# it has one; the name is used only when the `$uri` is empty.


def _twin_resources(db) -> tuple:
    name = f't{_tag()}_x'
    return _resource(db, name).id, _resource(db, name).id, name


def _acl_by_uri(resource_role_name: str, resource_id: int, name: str) -> dict:
    acl = _acl(resource_role_name, name)
    acl['resource']['$uri'] = f'/api2/resource/{resource_id}'
    return acl


def _group_with_acl(db, member, resource_role_name: str, resource_id: int):
    group = Group(name=f'group-{_tag()}', users=[db.session.query(User).get(member.id)])
    db.session.add(group)
    db.session.commit()
    _grant_group(db, group.id, resource_role_name, resource_id)
    return group.id, group.name


def test_adding_a_member_to_a_group_sharing_a_twin_keeps_its_acl(db, make_user):
    admin = make_user(['admin'])
    first_id, second_id, name = _twin_resources(db)
    group_id, group_name = _group_with_acl(db, admin, 'dashboard_viewer', second_id)
    member = make_user()

    response = admin.request(
        'PATCH',
        f'/api2/group/{group_id}',
        {
            '$uri': f'/api2/group/{group_id}',
            'name': group_name,
            'roles': [],
            'users': [admin.username, member.username],
            'acls': [_acl_by_uri('dashboard_viewer', second_id, name)],
        },
    )

    assert response.status_code == 200
    assert _group_acls(db, second_id) == {(group_id, 'dashboard_viewer')}
    assert _group_acls(db, first_id) == set()


def test_an_acl_uri_is_checked_for_update_users_on_that_resource(db, make_user):
    actor = make_user(['group_moderator'])
    shared_id, other_id, name = _twin_resources(db)
    _grant_user(db, actor.id, 'dashboard_admin', shared_id)
    # The actor can see the other twin, so refusing it reveals nothing.
    _grant_user(db, actor.id, 'dashboard_viewer', other_id)
    group_id, group_name = _group_with_acl(db, actor, 'dashboard_viewer', shared_id)

    response = actor.request(
        'PATCH',
        f'/api2/group/{group_id}',
        {
            '$uri': f'/api2/group/{group_id}',
            'name': group_name,
            'roles': [],
            'users': [actor.username],
            'acls': [
                _acl_by_uri('dashboard_viewer', shared_id, name),
                _acl_by_uri('dashboard_viewer', other_id, name),
            ],
        },
    )

    assert response.status_code == 403
    assert _group_acls(db, other_id) == set()


@pytest.mark.parametrize('named_by', ['uri', 'name'])
def test_an_acl_on_a_resource_the_caller_cannot_see_looks_like_no_resource(
    db, make_user, named_by
):
    actor = make_user(['group_moderator'])
    group_id, group_name = _group_with_acl(
        db, actor, 'dashboard_viewer', _resource(db, f'dashboard-{_tag()}').id
    )
    hidden_name = f'hidden-{_tag()}'
    hidden_id = _resource(db, hidden_name).id
    missing_name = f'missing-{_tag()}'

    def patch(acl):
        return actor.request(
            'PATCH',
            f'/api2/group/{group_id}',
            {
                '$uri': f'/api2/group/{group_id}',
                'name': group_name,
                'roles': [],
                'users': [actor.username],
                'acls': [acl],
            },
        )

    if named_by == 'uri':
        hidden = patch(_acl_by_uri('dashboard_viewer', hidden_id, hidden_name))
        missing = patch(_acl_by_uri('dashboard_viewer', 999999999, missing_name))
    else:
        hidden = patch(_acl('dashboard_viewer', hidden_name))
        missing = patch(_acl('dashboard_viewer', missing_name))

    assert (hidden.status_code, missing.status_code) == (404, 404)
    assert hidden.get_data(as_text=True).replace(
        hidden_name, 'NAME'
    ) == missing.get_data(as_text=True).replace(missing_name, 'NAME')
    assert _group_acls(db, hidden_id) == set()


@pytest.mark.parametrize('named_by', ['uri', 'name'])
def test_a_grant_on_a_hidden_resource_is_audited_by_id_only(db, make_user, named_by):
    actor = make_user(['group_moderator'])
    group_id, group_name = _group_with_acl(
        db, actor, 'dashboard_viewer', _resource(db, f'dashboard-{_tag()}').id
    )
    hidden_name = f'hidden-{_tag()}'
    hidden_id = _resource(db, hidden_name).id
    acl = (
        _acl_by_uri('dashboard_viewer', hidden_id, hidden_name)
        if named_by == 'uri'
        else _acl('dashboard_viewer', hidden_name)
    )
    handler = _Records()
    app_logger = logging.getLogger('ZenysisLogger')
    app_logger.addHandler(handler)
    try:
        response = actor.request(
            'PATCH',
            f'/api2/group/{group_id}',
            {
                '$uri': f'/api2/group/{group_id}',
                'name': group_name,
                'roles': [],
                'users': [actor.username],
                'acls': [acl],
            },
        )
    finally:
        app_logger.removeHandler(handler)

    assert response.status_code == 404
    refusals = [line for line in handler.lines if 'Refused grant' in line]
    assert len(refusals) == 1
    assert f'Resource id: {hidden_id}.' in refusals[0]
    assert hidden_name not in refusals[0]


@pytest.mark.parametrize(
    ('uri', 'status'),
    [('/api2/resource/not-an-id', 400), ('/api2/resource/999999999', 404)],
)
def test_an_acl_uri_naming_no_resource_is_refused(app, db, make_user, uri, status):
    admin = make_user(['admin'])
    target_id = _account(app, db, f'target-{_tag()}@named.test')
    db.session.expire_all()
    target = db.session.query(User).get(target_id)
    acl = _acl('dashboard_viewer', f'dashboard-{_tag()}')
    acl['resource']['$uri'] = uri

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
            'acls': [acl],
            'apiTokens': [],
            'roles': [],
            'groups': [],
        },
    )

    assert response.status_code == status
    db.session.expire_all()
    assert db.session.query(User).get(target_id).acls == []


@pytest.mark.parametrize('target', ['user', 'group'])
def test_deleting_a_role_on_a_look_alike_name_removes_nothing(
    app, db, make_user, target
):
    admin = make_user(['admin'])
    tag = _tag()
    look_alike_id = _resource(db, f'{tag}x{tag}').id
    if target == 'user':
        target_id = _account(app, db, f'target-{tag}@named.test')
        _grant_user(db, target_id, 'dashboard_viewer', look_alike_id)
    else:
        target_id = _group(db, f'group-{tag}').id
        _grant_group(db, target_id, 'dashboard_viewer', look_alike_id)

    response = admin.request(
        'DELETE',
        f'/api2/{target}/{target_id}/roles',
        {
            'roleName': 'dashboard_viewer',
            'resourceType': 'DASHBOARD',
            'resourceName': f'{tag}_{tag}',
        },
    )

    assert response.status_code == 404
    held = _user_acls(db, look_alike_id) | _group_acls(db, look_alike_id)
    assert held == {(target_id, 'dashboard_viewer')}


# Round 2, reviewer item 1: WP-0l must not merge without WP-0k. Before WP-0k,
# login checks the typed username with Flask-User's case-insensitive LIKE and
# signs the typed string into the JWT; the session loader then resolves that
# string. With exact matching in the loader alone, `x.doe` typing `x_doe` and
# its own password is signed in as `x_doe`. WP-0k signs `user.username`.


@pytest.mark.xfail(
    strict=True,
    reason='WP-0k signs the matched account into the JWT; passes once 0k merges',
)
def test_signing_in_with_a_look_alike_username_never_acts_as_its_account(app, db):
    tag = _tag()
    own_password = f'own-{tag}-password'
    victim_password = f'victim-{tag}-password'
    for username, password in (
        (f'{tag}.doe@named.test', own_password),
        (f'{tag}_doe@named.test', victim_password),
    ):
        db.session.add(
            User(
                username=username,
                password=app.user_manager.hash_password(password),
                first_name='Named',
                last_name='Lookup',
                status_id=UserStatusEnum.ACTIVE.value,
            )
        )
    db.session.commit()
    victim_id = db.session.query(User).filter_by(username=f'{tag}_doe@named.test')
    victims_dashboard = _resource(db, f'dashboard-{tag}').id
    _grant_user(db, victim_id.one().id, 'dashboard_viewer', victims_dashboard)
    client = app.test_client()

    login = client.post(
        '/api2/authentication/login?set_cookie=false',
        json={
            'email': f'{tag}_doe@named.test',
            'password': own_password,
            'remember_me': False,
        },
    )
    token = login.get_json().get('access_token') if login.status_code == 200 else None
    response = client.get(
        f'/api2/resource/{victims_dashboard}/roles',
        headers={'Authorization': f'Bearer {token}'} if token else {},
    )

    assert response.status_code in (401, 403)


# Round 3 (reviewer r2 F2): sharing the second of two same-named resources with
# a group lands on that one. Both rows are equal by name, so only acting on the
# resource in the URL can pick the second.


def test_sharing_the_second_twin_with_a_group_lands_on_it(db, make_user):
    name = f't{_tag()}_x'
    first_id = _resource(db, name).id
    second_id = _resource(db, name).id
    actor = make_user()
    _grant_user(db, actor.id, 'dashboard_admin', second_id)
    group = _group(db, f'group-{_tag()}')
    group_id, group_name = group.id, group.name

    response = _share(
        actor,
        second_id,
        {actor.username: ['dashboard_admin']},
        {group_name: ['dashboard_viewer']},
    )

    assert response.status_code == 204
    assert _group_acls(db, second_id) == {(group_id, 'dashboard_viewer')}
    assert _group_acls(db, first_id) == set()


# Round 3 (reviewer r2 F3): a share naming a resource role that does not exist,
# or one of another resource type, writes nothing, the sitewide ACL included.


@pytest.mark.parametrize('principal', ['user', 'group'])
@pytest.mark.parametrize('role_name', ['no_such_role', 'alert_admin'])
def test_a_share_naming_a_role_it_cannot_grant_writes_nothing(
    db, make_user, principal, role_name
):
    dashboard_id = _resource(db, f'dashboard-{_tag()}').id
    actor = make_user()
    _grant_user(db, actor.id, 'dashboard_admin', dashboard_id)
    other = make_user()
    group_name = _group(db, f'group-{_tag()}').name
    user_roles = {actor.username: ['dashboard_admin']}
    group_roles = {}
    if principal == 'user':
        user_roles[other.username] = [role_name]
    else:
        group_roles[group_name] = [role_name]

    response = actor.request(
        'POST',
        f'/api2/resource/{dashboard_id}/roles',
        {
            'userRoles': user_roles,
            'groupRoles': group_roles,
            'sitewideResourceAcl': {
                'registeredResourceRole': 'dashboard_viewer',
                'unregisteredResourceRole': '',
            },
        },
    )

    assert response.status_code == 404
    db.session.expire_all()
    assert (
        db.session.query(SitewideResourceAcl).filter_by(resource_id=dashboard_id).all()
        == []
    )
    assert _user_acls(db, dashboard_id) == {(actor.id, 'dashboard_admin')}
    assert _group_acls(db, dashboard_id) == set()
