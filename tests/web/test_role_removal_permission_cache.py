'''Taking a role away takes its rights away on the next request (INV-3).

User.get_permissions is memoized for CACHE_DEFAULT_TIMEOUT (10 minutes). Before
this fix neither role route cleared it: PATCH /api2/role/<id>/users cleared
nothing, and POST /api2/resource/<id>/roles deleted `cache[username]`, which is
never a key the memo uses. A user removed from the site admin role, a
query-policy role or a dashboard kept those rights until the entry expired.

Synthetic data on SQLite; nothing leaves the process.
'''

import contextlib
import importlib
import os
import pkgutil

import pytest
from flask import Flask, g
from flask_caching import Cache
from flask_principal import ItemNeed, RoleNeed

# config/settings.py reads these at import time; the values are test-only placeholders.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-web-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('ZEN_ENV', 'harmony_demo')

# pylint: disable=wrong-import-position
import models.alchemy
import web.server.security.permissions
from log import LOG
from models.alchemy.permission import (
    Permission,
    Resource,
    ResourceRole,
    ResourceRolePermission,
    ResourceType,
    ResourceTypeEnum,
    Role,
    RolePermissions,
    SitewideResourceAcl,
)
from models.alchemy.query_policy import (
    QueryPolicy,
    QueryPolicyRole,
    QueryPolicyType,
    QueryPolicyTypeEnum,
)
from models.alchemy.security_group import Group, GroupAcl, GroupRoles, GroupUsers
from models.alchemy.user import User, UserAcl, UserRoles, UserStatus, UserStatusEnum
from config.loader import import_configuration_module
from models.python.permissions import QueryNeed
from web.server.app_db import create_db

# User's relationships only configure once every model is registered.
for _module in pkgutil.iter_modules(models.alchemy.__path__):
    importlib.import_module(f'models.alchemy.{_module.name}')

ALICE = 'alice@example.org'
EVE = 'eve@example.org'
NO_SITEWIDE_ACL = {'registeredResourceRole': '', 'unregisteredResourceRole': ''}
ADMIN = RoleNeed('admin')


@pytest.fixture(name='app', scope='module')
def fixture_app():
    here = os.path.dirname(__file__)
    app = Flask('tests.web', root_path=here, instance_path=here)
    app.config.update(
        SQLALCHEMY_DATABASE_URI='sqlite://',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY='tests-web-placeholder-key',
    )
    db = create_db()
    db.init_app(app)
    # Production keeps entries for 10 minutes; nothing here expires.
    app.cache = Cache(
        app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 600}
    )
    # get_db_adapter() reads the flask-user adapter's session.
    app.user_manager = type('UserManager', (), {'db_adapter': db})()
    # The API modules read the deployment's filters at import.
    app.zen_config = import_configuration_module('harmony_demo')

    with app.app_context():
        models_used = [
            UserStatus,
            User,
            ResourceType,
            Resource,
            Permission,
            ResourceRole,
            ResourceRolePermission,
            Role,
            RolePermissions,
            UserRoles,
            UserAcl,
            Group,
            GroupUsers,
            GroupRoles,
            GroupAcl,
            SitewideResourceAcl,
            QueryPolicyType,
            QueryPolicy,
            QueryPolicyRole,
        ]
        db.Model.metadata.create_all(
            db.engine, tables=[model.__table__ for model in models_used]
        )
        db.session.add_all(UserStatus(id=s.value, status=s) for s in UserStatusEnum)
        db.session.add_all(ResourceType(id=t.value, name=t) for t in ResourceTypeEnum)
        db.session.add_all(
            QueryPolicyType(id=t.value, name=t) for t in QueryPolicyTypeEnum
        )
        dashboard_type = ResourceTypeEnum.DASHBOARD.value
        view = Permission(resource_type_id=dashboard_type, permission='view_resource')
        edit = Permission(resource_type_id=dashboard_type, permission='edit_resource')
        db.session.add_all([view, edit])
        db.session.flush()
        for name, permissions in (
            ('dashboard_viewer', [view]),
            ('dashboard_admin', [view, edit]),
        ):
            resource_role = ResourceRole(name=name, resource_type_id=dashboard_type)
            db.session.add(resource_role)
            db.session.flush()
            db.session.add_all(
                ResourceRolePermission(
                    resource_role_id=resource_role.id, permission_id=permission.id
                )
                for permission in permissions
            )
        db.session.add(
            Resource(resource_type_id=dashboard_type, name='jsc', label='JSC')
        )
        # SQLite rejects the 'false' server default, so set it.
        db.session.add(Role(name='admin', label='Site Admin', enable_data_export=False))
        policy = QueryPolicy(
            dimension='StateName',
            dimension_value='Lagos',
            query_policy_type_id=QueryPolicyTypeEnum.DIMENSION.value,
        )
        state_role = Role(name='lagos_data', label='Lagos', enable_data_export=False)
        db.session.add_all([policy, state_role])
        db.session.flush()
        db.session.add(
            QueryPolicyRole(query_policy_id=policy.id, role_id=state_role.id)
        )
        db.session.commit()
        yield app


@pytest.fixture(name='api', scope='module')
def fixture_api(app):
    with app.app_context():
        return importlib.import_module('web.server.api.permission_api_models')


@pytest.fixture(name='request_context')
def fixture_request_context(app, api, monkeypatch):
    # Every account here is signed in, so the public-dashboard check is False.
    monkeypatch.setattr(
        web.server.security.permissions, 'is_public_dashboard_user', lambda: False
    )
    # The routes' own permission check is not under test.
    monkeypatch.setattr(
        api,
        'AuthorizedOperation',
        lambda *_: contextlib.nullcontext(),
    )
    with app.test_request_context():
        g.request_logger = LOG
        yield
    db = _db(app)
    db.session.rollback()
    for model in (GroupAcl, GroupUsers, Group, UserAcl, UserRoles, User):
        db.session.query(model).delete()
    db.session.query(SitewideResourceAcl).delete()
    db.session.commit()
    app.cache.clear()


def _db(app):
    return app.extensions['sqlalchemy'].db


def _load(app, user_id):
    '''Load the account the way the next request does: in a fresh session.'''
    db = _db(app)
    db.session.remove()
    return db.session.query(User).get(user_id)


def _one(app, model, **fields):
    return _db(app).session.query(model).filter_by(**fields).one()


def _add_user(app, username, roles=()):
    db = _db(app)
    user = User(
        username=username,
        password='not-a-real-hash',
        status_id=UserStatusEnum.ACTIVE.value,
    )
    user.roles = [_one(app, Role, name=name) for name in roles]
    db.session.add(user)
    db.session.commit()
    return user.id


def _grant_dashboard(app, user_id, role_name):
    db = _db(app)
    db.session.add(
        UserAcl(
            user_id=user_id,
            resource_id=_one(app, Resource, name='jsc').id,
            resource_role_id=_one(app, ResourceRole, name=role_name).id,
        )
    )
    db.session.commit()


def _permissions(app, user_id):
    return _load(app, user_id).get_permissions()


def _dashboard_need(app, permission='view_resource'):
    return ItemNeed(permission, _one(app, Resource, name='jsc').id, 'dashboard')


def _lagos_need(app):
    return QueryNeed(_one(app, QueryPolicy, dimension_value='Lagos').dimension_filters)


def _set_role_users(app, role_name, usernames):
    '''PATCH /api2/role/<id>/users, as RoleResource.update_users runs it.'''
    role = _one(app, Role, name=role_name)
    api = importlib.import_module('web.server.api.permission_api_models')
    view = api.RoleResource.update_users.view_func
    view(None, role, usernames)


def _set_dashboard_roles(app, user_roles, group_roles=None, sitewide_acl=None):
    '''POST /api2/resource/<id>/roles, as BackendResource.update_resource_roles
    runs it.'''
    resource = _one(app, Resource, name='jsc')
    api = importlib.import_module('web.server.api.permission_api_models')
    view = api.BackendResource.update_resource_roles.view_func
    view(
        None,
        resource,
        {
            'userRoles': user_roles,
            'groupRoles': group_roles or {},
            'sitewideResourceAcl': sitewide_acl or NO_SITEWIDE_ACL,
        },
    )


@pytest.mark.usefixtures('request_context')
def test_removing_a_user_from_the_admin_role_clears_their_admin_rights(app):
    alice = _add_user(app, ALICE, roles=['admin'])
    eve = _add_user(app, EVE, roles=['admin'])
    assert ADMIN in _permissions(app, eve)

    _set_role_users(app, 'admin', [ALICE])

    assert ADMIN not in _permissions(app, eve)
    assert ADMIN in _permissions(app, alice)


@pytest.mark.usefixtures('request_context')
def test_removing_a_user_from_a_query_policy_role_clears_the_policy(app):
    eve = _add_user(app, EVE, roles=['lagos_data'])
    assert _lagos_need(app) in _permissions(app, eve)

    _set_role_users(app, 'lagos_data', [])

    assert _lagos_need(app) not in _permissions(app, eve)


@pytest.mark.usefixtures('request_context')
def test_adding_a_user_to_a_role_takes_effect_at_once(app):
    eve = _add_user(app, EVE)
    assert ADMIN not in _permissions(app, eve)

    _set_role_users(app, 'admin', [EVE])

    assert ADMIN in _permissions(app, eve)


@pytest.mark.usefixtures('request_context')
def test_removing_a_user_from_a_dashboard_clears_their_dashboard_rights(app):
    alice = _add_user(app, ALICE)
    eve = _add_user(app, EVE)
    _grant_dashboard(app, alice, 'dashboard_admin')
    _grant_dashboard(app, eve, 'dashboard_viewer')
    assert _dashboard_need(app) in _permissions(app, eve)

    _set_dashboard_roles(app, {ALICE: ['dashboard_admin']})

    assert _dashboard_need(app) not in _permissions(app, eve)
    assert _dashboard_need(app, 'edit_resource') in _permissions(app, alice)


@pytest.mark.usefixtures('request_context')
def test_removing_a_group_from_a_dashboard_clears_its_members_rights(app):
    alice = _add_user(app, ALICE)
    eve = _add_user(app, EVE)
    _grant_dashboard(app, alice, 'dashboard_admin')
    db = _db(app)
    group = Group(name='viewers')
    db.session.add(group)
    db.session.flush()
    db.session.add(GroupUsers(group_id=group.id, user_id=eve))
    db.session.add(
        GroupAcl(
            group_id=group.id,
            resource_id=_one(app, Resource, name='jsc').id,
            resource_role_id=_one(app, ResourceRole, name='dashboard_viewer').id,
        )
    )
    db.session.commit()
    assert _dashboard_need(app) in _permissions(app, eve)

    _set_dashboard_roles(app, {ALICE: ['dashboard_admin']}, group_roles={})

    assert _dashboard_need(app) not in _permissions(app, eve)


@pytest.mark.usefixtures('request_context')
def test_removing_the_sitewide_dashboard_role_clears_every_users_rights(app):
    alice = _add_user(app, ALICE)
    eve = _add_user(app, EVE)
    _grant_dashboard(app, alice, 'dashboard_admin')
    registered_viewers = {
        'registeredResourceRole': 'dashboard_viewer',
        'unregisteredResourceRole': '',
    }
    _set_dashboard_roles(
        app, {ALICE: ['dashboard_admin']}, sitewide_acl=registered_viewers
    )
    assert _dashboard_need(app) in _permissions(app, eve)

    _set_dashboard_roles(app, {ALICE: ['dashboard_admin']})

    assert _dashboard_need(app) not in _permissions(app, eve)
