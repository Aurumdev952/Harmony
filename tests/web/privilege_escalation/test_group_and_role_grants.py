'''WP-0h (decisions 0003 and 0004): a non-superuser may attach to a group, or put
into a role, only grants it already holds. Each escalation case is paired with
the nearby behaviour that must not change (SPEC INV-3).
'''

from __future__ import annotations

import logging
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
    label: str,
    permissions=(),
    dashboard_role='',
    alert_role='',
    query_policies=(),
    export=False,
):
    return {
        '$uri': '',
        'name': '',
        'label': label,
        'alertResourceRoleName': alert_role,
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


def _user_ids(group) -> list:
    return sorted(user.id for user in group.users)


def _role_names(db) -> set:
    db.session.expire_all()
    return {role.name for role in db.session.query(Role).all()}


# Groups: escalation 1 (WP-2b), group_admin creates a group holding the admin role.


def test_group_admin_cannot_create_a_group_holding_the_admin_role(db, make_user):
    actor = make_user(['group_admin'])
    name = _name('group')

    response = actor.request(
        'POST', '/api2/group', _group_body(name, roles=[_role_uri(db, 'admin')])
    )

    assert response.status_code == 403
    assert _group(db, name) is None
    assert _roles_of(db, actor) == {'group_admin'}


def test_a_refused_grant_is_audited_with_the_caller(db, make_user, caplog):
    actor = make_user(['group_admin'])
    # The app logger does not propagate to the root logger caplog listens on.
    app_logger = logging.getLogger('ZenysisLogger')
    app_logger.addHandler(caplog.handler)
    try:
        actor.request(
            'POST',
            '/api2/group',
            _group_body(_name('group'), roles=[_role_uri(db, 'admin')]),
        )
    finally:
        app_logger.removeHandler(caplog.handler)

    refusals = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and 'Refused grant' in record.getMessage()
    ]
    assert len(refusals) == 1
    assert actor.username in refusals[0]
    assert "['admin']" in refusals[0]


def test_group_admin_creates_a_group_with_a_role_it_holds_and_joins_it(db, make_user):
    actor = make_user(['group_admin'])
    name = _name('group')

    response = actor.request(
        'POST', '/api2/group', _group_body(name, roles=[_role_uri(db, 'group_admin')])
    )

    assert response.status_code == 200
    group = _group(db, name)
    assert [role.name for role in group.roles] == ['group_admin']
    assert _user_ids(group) == [actor.id]


def test_a_role_uri_naming_no_role_is_still_skipped(db, make_user):
    actor = make_user(['group_admin'])
    name = _name('group')

    response = actor.request(
        'POST', '/api2/group', _group_body(name, roles=['/api2/role/999999'])
    )

    assert response.status_code == 200
    assert _group(db, name).roles == []


def test_a_malformed_role_uri_is_a_bad_request(db, make_user):
    actor = make_user(['group_admin'])
    name = _name('group')

    response = actor.request(
        'POST', '/api2/group', _group_body(name, roles=['/api2/role/admin'])
    )

    assert response.status_code == 400
    assert _group(db, name) is None


def test_admin_creates_a_group_holding_the_admin_role(db, make_user):
    admin = make_user(['admin'])
    name = _name('group')

    response = admin.request(
        'POST', '/api2/group', _group_body(name, roles=[_role_uri(db, 'admin')])
    )

    assert response.status_code == 200
    assert [role.name for role in _group(db, name).roles] == ['admin']


def test_group_admin_cannot_create_a_group_holding_a_dashboard_it_cannot_share(
    db, make_user
):
    actor = make_user(['group_admin'])
    dashboard = _make_dashboard(db)
    name = _name('group')

    response = actor.request(
        'POST',
        '/api2/group',
        _group_body(name, acls=[_acl('dashboard_admin', dashboard)]),
    )

    assert response.status_code == 403
    assert _group(db, name) is None


def test_an_admin_token_narrowed_to_groups_cannot_grant_admin(app, db, make_user):
    # pylint: disable=import-outside-toplevel
    from flask_jwt_extended import create_access_token

    admin = make_user(['admin'])
    group = _make_group(db, users=[admin])
    group_id, group_name = group.id, group.name
    group_needs = [
        [permission, None, 'group']
        for permission in ('view_resource', 'edit_resource', 'create_resource')
    ]
    with app.test_request_context():
        token = create_access_token(
            identity=admin.username,
            user_claims={'needs': group_needs, 'query_needs': []},
        )
    client = app.test_client()
    client.set_cookie('localhost', 'accessKey', token)

    response = client.patch(
        f'/api2/group/{group_id}',
        json=_group_body(group_name, roles=[_role_uri(db, 'admin')], users=[admin]),
    )

    assert response.status_code == 403
    assert _group(db, group_name).roles == []


# Groups: escalation 2 (WP-2b), a member with edit_resource on group attaches admin.


def test_group_moderator_cannot_attach_the_admin_role_to_its_group(db, make_user):
    actor = make_user(['group_moderator'])
    other = make_user()
    group = _make_group(db, users=[actor])
    group_id, group_name = group.id, group.name

    response = actor.request(
        'PATCH',
        f'/api2/group/{group_id}',
        _group_body(group_name, roles=[_role_uri(db, 'admin')], users=[actor, other]),
    )

    assert response.status_code == 403
    group = _group(db, group_name)
    assert group.roles == []
    assert _user_ids(group) == [actor.id]
    assert _roles_of(db, actor) == {'group_moderator'}


# N5 (decision 0004): the same PATCH with a role carrying query policies.


def test_group_moderator_cannot_attach_a_role_carrying_data_it_cannot_read(
    db, make_user
):
    actor = make_user(['group_moderator'])
    group = _make_group(db, users=[actor])
    group_id, group_name = group.id, group.name

    response = actor.request(
        'PATCH',
        f'/api2/group/{group_id}',
        _group_body(
            group_name, roles=[_role_uri(db, 'all_sources_reader')], users=[actor]
        ),
    )

    assert response.status_code == 403
    assert _group(db, group_name).roles == []


def test_group_moderator_renames_a_group_keeping_grants_it_could_not_make(
    db, make_user
):
    # A viewer ACL gives members no update_users there, so only the resend
    # exemption lets it through.
    actor = make_user(['group_moderator'])
    dashboard = _make_dashboard(db)
    dashboard_id = dashboard.id
    viewer = db.session.query(ResourceRole).filter_by(name='dashboard_viewer').one()
    group = _make_group(
        db, roles=['all_sources_reader'], users=[actor], acls=[(viewer, dashboard)]
    )
    new_name = _name('renamed')

    response = actor.request(
        'PATCH',
        f'/api2/group/{group.id}',
        _group_body(
            new_name,
            roles=[_role_uri(db, 'all_sources_reader')],
            users=[actor],
            acls=[_acl('dashboard_viewer', dashboard)],
        ),
    )

    assert response.status_code == 200
    renamed = _group(db, new_name)
    assert [role.name for role in renamed.roles] == ['all_sources_reader']
    assert [(acl.resource_role.name, acl.resource_id) for acl in renamed.acls] == [
        ('dashboard_viewer', dashboard_id)
    ]


def test_group_moderator_reaches_only_groups_it_belongs_to(db, make_user):
    actor = make_user(['group_moderator'])
    group = _make_group(db, roles=['admin'])
    group_id, group_name = group.id, group.name

    responses = [
        actor.request('GET', f'/api2/group/{group_id}'),
        actor.request('POST', f'/api2/group/{group_id}/users', actor.username),
        actor.request('PATCH', f'/api2/group/{group_id}/users', [actor.username]),
        actor.request(
            'PATCH',
            f'/api2/group/{group_id}',
            _group_body(group_name, roles=[_role_uri(db, 'admin')], users=[actor]),
        ),
    ]

    assert [response.status_code for response in responses] == [404] * 4
    assert _group(db, group_name).users.all() == []
    assert _roles_of(db, actor) == {'group_moderator'}


# Group ACLs (found while closing escalation 2): resource roles on any dashboard.


def test_group_moderator_cannot_grant_its_group_admin_of_a_dashboard_it_cannot_share(
    db, make_user
):
    actor = make_user(['group_moderator'])
    group = _make_group(db, users=[actor])
    group_id, group_name = group.id, group.name
    dashboard = _make_dashboard(db)

    response = actor.request(
        'PATCH',
        f'/api2/group/{group_id}',
        _group_body(
            group_name, users=[actor], acls=[_acl('dashboard_admin', dashboard)]
        ),
    )

    assert response.status_code == 403
    assert _group(db, group_name).acls == []


def test_a_group_acl_without_a_resource_is_a_bad_request(db, make_user):
    actor = make_user(['group_moderator', 'dashboard_admin'])
    group = _make_group(db, users=[actor])
    group_id, group_name = group.id, group.name
    acl = _acl('dashboard_admin', _make_dashboard(db))
    acl['resource']['name'] = ''

    response = actor.request(
        'PATCH',
        f'/api2/group/{group_id}',
        _group_body(group_name, users=[actor], acls=[acl]),
    )

    assert response.status_code == 400
    assert _group(db, group_name).acls == []


def test_dashboard_admin_shares_a_dashboard_with_its_group(db, make_user):
    actor = make_user(['group_moderator', 'dashboard_admin'])
    group = _make_group(db, users=[actor])
    group_id, group_name = group.id, group.name
    dashboard = _make_dashboard(db)

    response = actor.request(
        'PATCH',
        f'/api2/group/{group_id}',
        _group_body(
            group_name, users=[actor], acls=[_acl('dashboard_viewer', dashboard)]
        ),
    )

    assert response.status_code == 200
    assert [acl.resource_role.name for acl in _group(db, group_name).acls] == [
        'dashboard_viewer'
    ]


# The legacy /roles sub-routes deleted Role rows themselves (decision 0004).


def test_clearing_a_groups_roles_keeps_the_roles(db, make_user):
    actor = make_user(['group_moderator'])
    held = Role(name=_name('held'), label='held')
    db.session.add(held)
    db.session.commit()
    held_name = held.name
    group = _make_group(db, roles=[held_name], users=[actor])
    group_id, group_name = group.id, group.name

    response = actor.request('PATCH', f'/api2/group/{group_id}/roles', {})

    assert response.status_code == 200
    assert held_name in _role_names(db)
    assert _group(db, group_name).roles == []


def test_clearing_a_users_roles_keeps_the_roles(db, make_user):
    actor = make_user(['user_admin'])
    held = Role(name=_name('held'), label='held')
    db.session.add(held)
    db.session.commit()
    held_name = held.name
    target = make_user([held_name])

    response = actor.request('PATCH', f'/api2/user/{target.id}/roles', {})

    assert response.status_code == 200
    assert held_name in _role_names(db)
    assert _roles_of(db, target) == set()


# Roles: escalation 3 (WP-2b), role_administrator creates a role with any grant.


def _role_by_label(db, label: str):
    db.session.expire_all()
    return db.session.query(Role).filter_by(label=label).one_or_none()


@pytest.mark.parametrize(
    'grant',
    [
        {'permissions': [('SITE', 'view_admin_page')]},
        {'dashboard_role': 'dashboard_admin'},
        {'alert_role': 'alert_admin'},
    ],
    ids=['permission', 'dashboard_resource_role', 'alert_resource_role'],
)
def test_role_administrator_cannot_create_a_role_with_permissions(db, make_user, grant):
    actor = make_user(['role_administrator'])
    label = _name('role')

    response = actor.request('POST', '/api2/role', _role_body(label, **grant))

    assert response.status_code == 403
    assert _role_by_label(db, label) is None
    assert _roles_of(db, actor) == {'role_administrator'}


# N4 (decision 0004): query policies and data export the creator does not hold.


def test_role_administrator_cannot_create_a_role_reading_data_it_cannot_read(
    db, make_user
):
    actor = make_user(['role_administrator'])
    label = _name('role')

    response = actor.request(
        'POST',
        '/api2/role',
        _role_body(label, query_policies=[_policy(db, 'source', None)]),
    )

    assert response.status_code == 403
    assert _role_by_label(db, label) is None


def test_role_administrator_cannot_create_a_role_exporting_data(db, make_user):
    actor = make_user(['role_administrator'])
    label = _name('role')

    response = actor.request('POST', '/api2/role', _role_body(label, export=True))

    assert response.status_code == 403
    assert _role_by_label(db, label) is None


def test_role_administrator_creates_an_empty_role_and_is_added_to_it(db, make_user):
    actor = make_user(['role_administrator'])
    label = _name('role')

    response = actor.request('POST', '/api2/role', _role_body(label))

    assert response.status_code == 200
    assert _roles_of(db, actor) == {'role_administrator', label}


@pytest.mark.parametrize('browser', [False, True], ids=['headers', 'browser_session'])
def test_role_administrator_creates_a_role_with_grants_it_holds_and_is_added(
    db, make_user, browser
):
    actor = make_user(
        ['role_administrator', 'all_sources_reader', 'exporter'], browser=browser
    )
    label = _name('role')

    response = actor.request(
        'POST',
        '/api2/role',
        _role_body(label, query_policies=[_policy(db, 'source', None)], export=True),
    )

    assert response.status_code == 200
    assert label in _roles_of(db, actor)


def test_a_holder_of_update_permissions_creates_a_role_with_permissions(db, make_user):
    actor = make_user(['role_administrator', 'permission_editor'])
    label = _name('role')

    response = actor.request(
        'POST',
        '/api2/role',
        _role_body(label, permissions=[('SITE', 'view_admin_page')]),
    )

    assert response.status_code == 200
    assert [p.permission for p in _role_by_label(db, label).permissions] == [
        'view_admin_page'
    ]
    # It does not hold view_admin_page, so it is not added to the new role.
    assert _roles_of(db, actor) == {'role_administrator', 'permission_editor'}


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
            query_policies=[_policy(db, 'StateName', 'Kigali')],
            export=True,
        ),
    )

    assert response.status_code == 200
    role = _role_by_label(db, label)
    assert [p.permission for p in role.permissions] == ['view_admin_page']
    assert role.dashboard_resource_role.name == 'dashboard_admin'
    assert _roles_of(db, admin) == {'admin'}


# N3 (decision 0004): holders of edit_resource on role change a role they hold.


def _new_role(db, policies=(), export=False) -> int:
    role = Role(
        name=_name('held'),
        label='held',
        query_policies=list(policies),
        enable_data_export=export,
    )
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


def _policies_body(*policies) -> list:
    return _role_body('', query_policies=policies)['queryPolicies']


def _moderator_holding_a_role(db, make_user, also=(), **role):
    role_id = _new_role(db, **role)
    return make_user(['role_moderator', *also, _role(db, role_id).name]), role_id


@pytest.mark.parametrize(
    'change',
    [
        {'permissions': [{'permission': 'view_admin_page', 'resource_type_id': 1}]},
        {'dashboardResourceRoleName': 'dashboard_admin'},
        {'alertResourceRoleName': 'alert_admin'},
        {'dataExport': True},
    ],
    ids=['permission', 'dashboard_resource_role', 'alert_resource_role', 'export'],
)
def test_role_moderator_cannot_add_grants_to_a_role_it_holds(db, make_user, change):
    actor, role_id = _moderator_holding_a_role(db, make_user)

    response = actor.request(
        'PATCH', f'/api2/role/{role_id}', _patch_body(db, role_id, **change)
    )

    assert response.status_code == 403
    role = _role(db, role_id)
    assert role.permissions == []
    assert role.dashboard_resource_role_id is None
    assert role.alert_resource_role_id is None
    assert role.enable_data_export is False


def test_role_moderator_cannot_add_data_it_cannot_read_to_a_role_it_holds(
    db, make_user
):
    actor, role_id = _moderator_holding_a_role(db, make_user)
    body = _patch_body(
        db, role_id, queryPolicies=_policies_body(_policy(db, 'source', None))
    )

    response = actor.request('PATCH', f'/api2/role/{role_id}', body)

    assert response.status_code == 403
    assert _role(db, role_id).query_policies == []


def test_role_moderator_adds_data_it_already_reads_to_a_role_it_holds(db, make_user):
    actor, role_id = _moderator_holding_a_role(
        db, make_user, also=['all_sources_reader']
    )
    body = _patch_body(
        db, role_id, queryPolicies=_policies_body(_policy(db, 'source', None))
    )

    response = actor.request('PATCH', f'/api2/role/{role_id}', body)

    assert response.status_code == 200
    assert [p.dimension for p in _role(db, role_id).query_policies] == ['source']


def test_role_moderator_relabels_a_role_it_holds_resending_its_grants(db, make_user):
    actor, role_id = _moderator_holding_a_role(
        db, make_user, policies=[_policy(db, 'StateName', 'Kigali')], export=True
    )

    response = actor.request(
        'PATCH', f'/api2/role/{role_id}', _patch_body(db, role_id, label='relabelled')
    )

    assert response.status_code == 200
    role = _role(db, role_id)
    assert role.label == 'relabelled'
    assert [p.dimension_value for p in role.query_policies] == ['Kigali']
    assert role.enable_data_export is True


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


# N6 (decision 0004): PATCH /api2/role/<id>/users confers a role on other users.


def test_role_moderator_confers_only_roles_it_holds(db, make_user):
    actor, held_id = _moderator_holding_a_role(db, make_user)
    other = make_user()
    not_held_id = _new_role(db)

    responses = [
        actor.request(
            'PATCH', f'/api2/role/{not_held_id}/users', [actor.username, other.username]
        ),
        actor.request(
            'PATCH', f'/api2/role/{held_id}/users', [actor.username, other.username]
        ),
    ]

    assert [response.status_code for response in responses] == [404, 200]
    assert _roles_of(db, actor) == {'role_moderator', _role(db, held_id).name}
    assert _roles_of(db, other) == {_role(db, held_id).name}
