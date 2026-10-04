'''WP-0h: a caller may attach to a group, or put into a role, only what it could
grant directly. Each escalation case is paired with the nearby behaviour that
must not change (SPEC INV-3).
'''

from __future__ import annotations

import uuid

import pytest

from models.alchemy.permission import Resource, ResourceRole, ResourceTypeEnum, Role
from models.alchemy.query_policy import QueryPolicy
from models.alchemy.security_group import Group, GroupAcl
from models.alchemy.user import User


@pytest.fixture(name='db')
def fixture_db(app):
    with app.app_context():
        yield app.extensions['sqlalchemy'].db


def _name(prefix: str) -> str:
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


def _role_uri(db, name: str) -> str:
    return f'/api2/role/{db.session.query(Role).filter_by(name=name).one().id}'


def _roles_of(db, actor) -> set:
    db.session.expire_all()
    return {role.name for role in db.session.query(User).get(actor.id).get_all_roles()}


def _group(db, name: str):
    db.session.expire_all()
    return db.session.query(Group).filter_by(name=name).one_or_none()


def _make_group(db, roles=(), users=(), acls=()) -> Group:
    group = Group(
        name=_name('group'),
        roles=[db.session.query(Role).filter_by(name=r).one() for r in roles],
        users=db.session.query(User).filter(User.id.in_([u.id for u in users])).all(),
    )
    db.session.add(group)
    db.session.flush()
    for resource_role, resource in acls:
        db.session.add(
            GroupAcl(
                group_id=group.id,
                resource_role_id=resource_role.id,
                resource_id=resource.id,
            )
        )
    db.session.commit()
    return group


def _make_dashboard(db) -> Resource:
    resource = Resource(
        resource_type_id=ResourceTypeEnum.DASHBOARD.value,
        name=_name('dashboard'),
        label='Dashboard',
    )
    db.session.add(resource)
    db.session.commit()
    return resource


def _acl(resource_role_name: str, dashboard: Resource) -> dict:
    return {
        '$uri': '',
        'resourceRole': {
            '$uri': '',
            'name': resource_role_name,
            'resourceType': 'DASHBOARD',
        },
        'resource': {
            '$uri': '',
            'label': dashboard.label,
            'name': dashboard.name,
            'resourceType': 'DASHBOARD',
        },
    }


def _group_body(group_name: str, roles=(), users=(), acls=(), uri='') -> dict:
    return {
        '$uri': uri,
        'name': group_name,
        'roles': list(roles),
        'users': [u.username for u in users],
        'acls': list(acls),
    }


def _role_body(
    label: str, permissions=(), dashboard_role='', query_policies=(), export=False
):
    return {
        '$uri': '',
        'name': '',
        'label': label,
        'alertResourceRoleName': '',
        'dashboardResourceRoleName': dashboard_role,
        'permissions': [
            {'permission': p, 'resource_type_id': ResourceTypeEnum[t].value}
            for t, p in permissions
        ],
        'queryPolicies': [
            {
                '$uri': f'/api2/query_policy/{policy.id}',
                'dimension': policy.dimension,
                'dimensionValue': policy.dimension_value,
                'queryPolicyTypeId': policy.query_policy_type_id,
            }
            for policy in query_policies
        ],
        'dataExport': export,
    }


def _policy(db, dimension: str, value) -> QueryPolicy:
    return (
        db.session.query(QueryPolicy)
        .filter_by(dimension=dimension, dimension_value=value)
        .one()
    )


# Escalation 1 (WP-2b): group_admin creates a group holding the admin role.


def test_group_admin_cannot_create_a_group_holding_the_admin_role(db, make_user):
    actor = make_user(['group_admin'])
    name = _name('group')

    response = actor.request(
        'POST', '/api2/group', _group_body(name, roles=[_role_uri(db, 'admin')])
    )

    assert response.status_code == 403
    assert _group(db, name) is None
    assert _roles_of(db, actor) == {'group_admin'}


def test_group_admin_creates_a_group_with_a_role_it_holds_and_joins_it(db, make_user):
    actor = make_user(['group_admin'])
    name = _name('group')

    response = actor.request(
        'POST', '/api2/group', _group_body(name, roles=[_role_uri(db, 'group_admin')])
    )

    assert response.status_code == 200
    group = _group(db, name)
    assert [role.name for role in group.roles] == ['group_admin']
    assert [user.id for user in group.users] == [actor.id]


def test_admin_creates_a_group_holding_the_admin_role(db, make_user):
    admin = make_user(['admin'])
    name = _name('group')

    response = admin.request(
        'POST', '/api2/group', _group_body(name, roles=[_role_uri(db, 'admin')])
    )

    assert response.status_code == 200
    assert [role.name for role in _group(db, name).roles] == ['admin']


# Escalation 2 (WP-2b): group_moderator patches its group's roles to include admin.


def test_group_moderator_cannot_attach_the_admin_role_to_its_group(db, make_user):
    actor = make_user(['group_moderator'])
    group = _make_group(db, users=[actor])

    response = actor.request(
        'PATCH',
        f'/api2/group/{group.id}',
        _group_body(group.name, roles=[_role_uri(db, 'admin')], users=[actor]),
    )

    assert response.status_code == 403
    assert _group(db, group.name).roles == []
    assert _roles_of(db, actor) == {'group_moderator'}


def test_group_moderator_renames_a_group_keeping_grants_it_could_not_make(
    db, make_user
):
    actor = make_user(['group_moderator'])
    dashboard = _make_dashboard(db)
    dashboard_admin = (
        db.session.query(ResourceRole).filter_by(name='dashboard_admin').one()
    )
    group = _make_group(
        db,
        roles=['dashboard_admin'],
        users=[actor],
        acls=[(dashboard_admin, dashboard)],
    )
    new_name = _name('renamed')

    response = actor.request(
        'PATCH',
        f'/api2/group/{group.id}',
        _group_body(
            new_name,
            roles=[_role_uri(db, 'dashboard_admin')],
            users=[actor],
            acls=[_acl('dashboard_admin', dashboard)],
        ),
    )

    assert response.status_code == 200
    renamed = _group(db, new_name)
    assert [role.name for role in renamed.roles] == ['dashboard_admin']
    assert [(acl.resource_role.name, acl.resource_id) for acl in renamed.acls] == [
        ('dashboard_admin', dashboard.id)
    ]


# Found while closing escalation 2: the same PATCH grants resource roles on any dashboard.


def test_group_moderator_cannot_grant_its_group_admin_of_a_dashboard_it_cannot_share(
    db, make_user
):
    actor = make_user(['group_moderator'])
    group = _make_group(db, users=[actor])
    dashboard = _make_dashboard(db)

    response = actor.request(
        'PATCH',
        f'/api2/group/{group.id}',
        _group_body(
            group.name, users=[actor], acls=[_acl('dashboard_admin', dashboard)]
        ),
    )

    assert response.status_code == 403
    assert _group(db, group.name).acls == []


def test_dashboard_admin_shares_a_dashboard_with_its_group(db, make_user):
    actor = make_user(['group_moderator', 'dashboard_admin'])
    group = _make_group(db, users=[actor])
    dashboard = _make_dashboard(db)

    response = actor.request(
        'PATCH',
        f'/api2/group/{group.id}',
        _group_body(
            group.name,
            roles=[],
            users=[actor],
            acls=[_acl('dashboard_viewer', dashboard)],
        ),
    )

    assert response.status_code == 200
    assert [acl.resource_role.name for acl in _group(db, group.name).acls] == [
        'dashboard_viewer'
    ]


# Escalation 3 (WP-2b): role_administrator creates a role with any permissions.


def test_role_administrator_cannot_create_a_role_with_permissions(db, make_user):
    actor = make_user(['role_administrator'])
    label = _name('role')

    response = actor.request(
        'POST',
        '/api2/role',
        _role_body(
            label,
            permissions=[('SITE', 'view_admin_page')],
            dashboard_role='dashboard_admin',
        ),
    )

    assert response.status_code == 403
    assert db.session.query(Role).filter_by(label=label).one_or_none() is None
    assert _roles_of(db, actor) == {'role_administrator'}


def test_role_administrator_cannot_create_a_role_with_a_resource_role(db, make_user):
    actor = make_user(['role_administrator'])
    label = _name('role')

    response = actor.request(
        'POST', '/api2/role', _role_body(label, dashboard_role='dashboard_admin')
    )

    assert response.status_code == 403
    assert db.session.query(Role).filter_by(label=label).one_or_none() is None


def test_role_administrator_creates_an_empty_role_and_is_added_to_it(db, make_user):
    actor = make_user(['role_administrator'])
    label = _name('role')

    response = actor.request('POST', '/api2/role', _role_body(label))

    assert response.status_code == 200
    assert _roles_of(db, actor) == {'role_administrator', label}


def test_role_administrator_is_added_to_a_new_role_granting_data_it_already_reads(
    db, make_user
):
    actor = make_user(['role_administrator', 'all_sources_reader'])
    label = _name('role')

    response = actor.request(
        'POST',
        '/api2/role',
        _role_body(label, query_policies=[_policy(db, 'source', None)]),
    )

    assert response.status_code == 200
    assert label in _roles_of(db, actor)


def test_role_administrator_is_not_added_to_a_new_role_granting_data_it_cannot_read(
    db, make_user
):
    actor = make_user(['role_administrator'])
    label = _name('role')

    response = actor.request(
        'POST',
        '/api2/role',
        _role_body(
            label, query_policies=[_policy(db, 'StateName', 'Kigali')], export=True
        ),
    )

    assert response.status_code == 200
    assert db.session.query(Role).filter_by(label=label).one().query_policies
    assert _roles_of(db, actor) == {'role_administrator'}


def test_admin_creates_a_role_with_permissions(db, make_user):
    admin = make_user(['admin'])
    label = _name('role')

    response = admin.request(
        'POST',
        '/api2/role',
        _role_body(
            label,
            permissions=[('SITE', 'view_admin_page')],
            dashboard_role='dashboard_admin',
        ),
    )

    assert response.status_code == 200
    role = db.session.query(Role).filter_by(label=label).one()
    assert [p.permission for p in role.permissions] == ['view_admin_page']
    assert role.dashboard_resource_role.name == 'dashboard_admin'


# Same hole as escalation 3 through PATCH: a role's holders edit its permissions.


def _new_role(db) -> int:
    role = Role(name=_name('held'), label='held')
    db.session.add(role)
    db.session.commit()
    return role.id


def _role(db, role_id: int) -> Role:
    db.session.expire_all()
    return db.session.query(Role).get(role_id)


def _patch_body(db, role_id: int, **changes) -> dict:
    role = _role(db, role_id)
    body = _role_body(
        role.label,
        permissions=[
            (p.resource_type.name.name, p.permission) for p in role.permissions
        ],
        dashboard_role=(
            role.dashboard_resource_role.name if role.dashboard_resource_role else ''
        ),
        query_policies=role.query_policies,
        export=role.enable_data_export,
    )
    body.update({'$uri': f'/api2/role/{role_id}', 'name': role.name}, **changes)
    return body


def _role_moderator_holding_a_role(db, make_user):
    role_id = _new_role(db)
    return make_user(['role_moderator', _role(db, role_id).name]), role_id


def test_role_moderator_cannot_add_permissions_to_a_role_it_holds(db, make_user):
    actor, role_id = _role_moderator_holding_a_role(db, make_user)
    body = _patch_body(
        db,
        role_id,
        permissions=[{'permission': 'view_admin_page', 'resource_type_id': 1}],
    )

    response = actor.request('PATCH', f'/api2/role/{role_id}', body)

    assert response.status_code == 403
    assert _role(db, role_id).permissions == []


def test_role_moderator_cannot_give_a_role_it_holds_a_resource_role(db, make_user):
    actor, role_id = _role_moderator_holding_a_role(db, make_user)
    body = _patch_body(db, role_id, dashboardResourceRoleName='dashboard_admin')

    response = actor.request('PATCH', f'/api2/role/{role_id}', body)

    assert response.status_code == 403
    assert _role(db, role_id).dashboard_resource_role_id is None


def test_role_moderator_cannot_give_a_role_it_holds_more_data(db, make_user):
    actor, role_id = _role_moderator_holding_a_role(db, make_user)
    body = _patch_body(
        db,
        role_id,
        dataExport=True,
        queryPolicies=_role_body('', query_policies=[_policy(db, 'source', None)])[
            'queryPolicies'
        ],
    )

    response = actor.request('PATCH', f'/api2/role/{role_id}', body)

    assert response.status_code == 403
    role = _role(db, role_id)
    assert role.query_policies == []
    assert role.enable_data_export is False


def test_role_moderator_relabels_a_role_it_holds(db, make_user):
    actor, role_id = _role_moderator_holding_a_role(db, make_user)
    body = _patch_body(db, role_id, label='relabelled')

    response = actor.request('PATCH', f'/api2/role/{role_id}', body)

    assert response.status_code == 200
    assert _role(db, role_id).label == 'relabelled'


def test_admin_adds_permissions_to_a_role(db, make_user):
    admin = make_user(['admin'])
    role_id = _new_role(db)
    body = _patch_body(
        db,
        role_id,
        permissions=[{'permission': 'view_admin_page', 'resource_type_id': 1}],
    )

    response = admin.request('PATCH', f'/api2/role/{role_id}', body)

    assert response.status_code == 200
    assert [p.permission for p in _role(db, role_id).permissions] == ['view_admin_page']
