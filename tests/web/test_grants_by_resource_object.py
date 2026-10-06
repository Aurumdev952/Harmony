'''Grants, shares and share removals act on the resource and principals they
were given, never on a row found again by name.

Resource and user lookups by name are ILIKE patterns taking the first row, and
dashboard names are slugified with underscores, so `a_b` also matches `axb`.
Dashboard creation, ownership transfer and sharing used to re-find the
resource they held by its name, and share removal re-found the principal, so
the grant or removal could land on a look-alike the caller has no rights on.
'''

import importlib
import json
import os
import pkgutil
from types import SimpleNamespace

# config.settings reads these at import time; these routes never use them.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-web-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')

# pylint: disable=wrong-import-position
import pytest
from flask import Flask, request_started
from flask_caching import Cache
from flask_login import LoginManager
from flask_potion import Api, ModelResource
from flask_potion.signals import after_create
from flask_principal import Principal, identity_loaded
from sqlalchemy import Boolean, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from werkzeug.exceptions import NotFound

import models.alchemy
from models.alchemy.dashboard import Dashboard, DashboardUserMetadata
from models.alchemy.permission import (
    Permission,
    Resource,
    ResourceRole,
    ResourceType,
    ResourceTypeEnum,
    Role,
)
from models.alchemy.security_group import Group, GroupAcl
from models.alchemy.user import User, UserAcl, UserRoles, UserStatus, UserStatusEnum
from web.server.api.dashboard_api_models import (
    DashboardResource,
    send_email_after_create,
)
from web.server.app_db import create_db
from web.server.configuration.settings import _populate_configuration_table
from web.server.data.data_access import Transaction
from web.server.database.alerts import make_author_alert_administrator
from web.server.potion.signals import after_roles_update
from web.server.routes.views.alerts import add_user_as_alert_administrator
from web.server.routes.views.core import try_get_role_and_resource
from web.server.routes.views.groups import replace_group_acls
from web.server.routes.views.users import replace_user_acls
from web.server.security.signal_handlers import (
    initialize_request_logger,
    install_identity_loader,
    on_identity_loaded,
)

# User's relationships only configure once every model is registered.
for _module in pkgutil.iter_modules(models.alchemy.__path__):
    importlib.import_module(f'models.alchemy.{_module.name}')

DASHBOARD_TYPE = ResourceTypeEnum.DASHBOARD.value
ALERT_TYPE = ResourceTypeEnum.ALERT.value
# What dashboard creation, transfer and sharing read and write.
TABLES = (
    'configuration',
    'dashboard',
    'dashboard_user_metadata',
    'permission',
    'query_policy',
    'query_policy_role',
    'resource',
    'resource_role',
    'resource_role_permission',
    'resource_type',
    'role',
    'role_permissions',
    'security_group',
    'security_group_acl',
    'security_group_roles',
    'security_group_users',
    'sitewide_resource_acl',
    'user',
    'user_acl',
    'user_roles',
    'user_status',
)

# john.doe has the lower id, so the pattern 'john_doe@...' finds john.doe first.
USER_IDS = {
    'alice@example.org': 1,
    'bob@example.org': 2,
    'carol@example.org': 3,
    'john.doe@example.org': 4,
    'john_doe@example.org': 5,
}
ALICE, BOB, CAROL, JOHN_DOT_DOE, JOHN_DOE = USER_IDS
GROUP_IDS = {'ops': 1}
ADMIN, VIEWER = 'dashboard_admin', 'dashboard_viewer'
NO_SITEWIDE_ACL = {'registeredResourceRole': '', 'unregisteredResourceRole': ''}


@compiles(JSONB, 'sqlite')
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return 'JSON'


def _store_unset_booleans_as_false(_mapper, _connection, target):
    # SQLite would store the server default 'false' as text, which fails the
    # Boolean check constraint.
    for column in target.__table__.columns:
        if isinstance(column.type, Boolean) and getattr(target, column.key) is None:
            setattr(target, column.key, False)


MODELS_WITH_FALSE_DEFAULTS = (Dashboard, DashboardUserMetadata, Role)


def _jsonb_extract_path_text(document, *path):
    # The Postgres function dashboard listings use to read a title.
    value = json.loads(document)
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _add_postgres_functions(connection, _record):
    connection.create_function('jsonb_extract_path_text', -1, _jsonb_extract_path_text)


# The resources under test relate to these by name.
class UserStub(ModelResource):
    class Meta:
        name = 'user'
        model = User
        include_fields = ('username',)


class GroupStub(ModelResource):
    class Meta:
        name = 'group'
        model = Group
        include_fields = ('name',)


# Potion lets a resource join one Api, hence the module scope, and adds the
# routes it registers to the resource. Another test module's Api may hold
# DashboardResource, so it is released before and after.
_DASHBOARD_ROUTES = dict(DashboardResource.routes)


def _release_dashboard_resource():
    DashboardResource.api = None
    DashboardResource.routes = dict(_DASHBOARD_ROUTES)


@pytest.fixture(name='app', scope='module')
def fixture_app():
    here = os.path.dirname(__file__)
    app = Flask('tests.web', root_path=here, instance_path=here)
    app.config.update(
        SQLALCHEMY_DATABASE_URI='sqlite://',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db = create_db()
    db.init_app(app)
    app.cache = Cache(app, config={'CACHE_TYPE': 'null'})
    # permission_api_models reads the deployment's filters at import time.
    app.zen_config = SimpleNamespace(
        filters=SimpleNamespace(AUTHORIZABLE_DIMENSIONS=[])
    )
    with app.app_context():
        permission_api = importlib.import_module('web.server.api.permission_api_models')

    login_manager = LoginManager(app)
    login_manager.request_loader(
        lambda request: User.query.get(int(request.headers['X-Test-User-Id']))
    )
    install_identity_loader(Principal(app, use_sessions=False))
    identity_loaded.connect(on_identity_loaded, app)
    request_started.connect(initialize_request_logger, app)
    _release_dashboard_resource()
    api = Api(app, prefix='/api2')
    for resource in (
        UserStub,
        GroupStub,
        permission_api.BackendTypeResource,
        permission_api.BackendResource,
        DashboardResource,
    ):
        api.add_resource(resource)

    # Notification emails need the full app and are not under test.
    after_create.disconnect(send_email_after_create, sender=DashboardResource)
    after_roles_update.disconnect(permission_api.send_email)
    for model in MODELS_WITH_FALSE_DEFAULTS:
        event.listen(model, 'before_insert', _store_unset_booleans_as_false)
    with app.app_context():
        event.listen(db.engine, 'connect', _add_postgres_functions)
        metadata = db.Model.metadata
        metadata.create_all(db.engine, tables=[metadata.tables[n] for n in TABLES])
        _seed_roles(db.session)
        yield app
    for model in MODELS_WITH_FALSE_DEFAULTS:
        event.remove(model, 'before_insert', _store_unset_booleans_as_false)
    after_roles_update.connect(permission_api.send_email)
    after_create.connect(send_email_after_create, sender=DashboardResource)
    _release_dashboard_resource()


def _seed_roles(session):
    _populate_configuration_table(session)
    session.add_all(UserStatus(id=s.value, status=s) for s in UserStatusEnum)
    session.add_all(ResourceType(id=t.value, name=t) for t in ResourceTypeEnum)
    view, edit, update_users, create = (
        Permission(resource_type_id=DASHBOARD_TYPE, permission=name)
        for name in (
            'view_resource',
            'edit_resource',
            'update_users',
            'create_resource',
        )
    )
    session.add_all(
        [
            ResourceRole(
                name=ADMIN,
                resource_type_id=DASHBOARD_TYPE,
                permissions=[view, edit, update_users],
            ),
            ResourceRole(
                name=VIEWER, resource_type_id=DASHBOARD_TYPE, permissions=[view]
            ),
            ResourceRole(
                name='alert_admin',
                resource_type_id=ALERT_TYPE,
                permissions=[
                    Permission(resource_type_id=ALERT_TYPE, permission='view_resource')
                ],
            ),
            Role(name='dashboard_creator', permissions=[create]),
        ]
    )
    session.commit()


@pytest.fixture(name='db', autouse=True)
def fixture_db(app):
    db = app.extensions['sqlalchemy'].db
    db.session.add_all(
        User(id=user_id, username=name, status_id=UserStatusEnum.ACTIVE.value)
        for name, user_id in USER_IDS.items()
    )
    db.session.add_all(
        Group(id=group_id, name=name) for name, group_id in GROUP_IDS.items()
    )
    db.session.commit()
    yield db
    db.session.rollback()
    for model in (
        GroupAcl,
        UserAcl,
        UserRoles,
        DashboardUserMetadata,
        Dashboard,
        Resource,
        Group,
        User,
    ):
        db.session.query(model).delete()
    db.session.commit()


def _add_dashboard(db, name, user_roles, group_roles=None):
    '''Adds the dashboard `name`, authored by the first user in `user_roles`.
    `user_roles` and `group_roles` map a user or group name to the role it
    holds on the dashboard. Returns the dashboard's resource id.
    '''
    resource = Resource(resource_type_id=DASHBOARD_TYPE, name=name, label=name)
    db.session.add(resource)
    db.session.flush()
    db.session.add(
        Dashboard(
            slug=name,
            specification={},
            resource_id=resource.id,
            author_id=USER_IDS[next(iter(user_roles))],
            is_official=False,
            registered_users_can_download_data=False,
            unregistered_users_can_download_data=False,
        )
    )
    db.session.add_all(
        UserAcl(
            user_id=USER_IDS[username],
            resource_id=resource.id,
            resource_role_id=_role_id(db, role_name),
        )
        for username, role_name in user_roles.items()
    )
    db.session.add_all(
        GroupAcl(
            group_id=GROUP_IDS[group_name],
            resource_id=resource.id,
            resource_role_id=_role_id(db, role_name),
        )
        for group_name, role_name in (group_roles or {}).items()
    )
    db.session.commit()
    return resource.id


def _role_id(db, role_name):
    return db.session.query(ResourceRole).filter_by(name=role_name).one().id


def _grants(db):
    '''Every grant, as (resource name, user or group name, role name).'''
    db.session.expire_all()
    grants = {
        (acl.resource.name, acl.user.username, acl.resource_role.name)
        for acl in db.session.query(UserAcl)
    }
    grants.update(
        (acl.resource.name, acl.group.name, acl.resource_role.name)
        for acl in db.session.query(GroupAcl)
    )
    return grants


def _post(app, caller, path, body):
    return app.test_client().post(
        f'/api2{path}', json=body, headers={'X-Test-User-Id': str(USER_IDS[caller])}
    )


def _share(app, caller, resource_id, user_roles, group_roles):
    return _post(
        app,
        caller,
        f'/resource/{resource_id}/roles',
        {
            'userRoles': user_roles,
            'groupRoles': group_roles,
            'sitewideResourceAcl': NO_SITEWIDE_ACL,
        },
    )


def test_creating_a_b_while_axb_exists_makes_the_author_admin_of_a_b_only(db, app):
    _add_dashboard(db, 'axb', {ALICE: ADMIN})
    creator = db.session.query(Role).filter_by(name='dashboard_creator').one()
    db.session.add(UserRoles(user_id=USER_IDS[BOB], role_id=creator.id))
    db.session.commit()

    response = _post(
        app,
        BOB,
        '/dashboard',
        {'slug': 'a_b', 'specification': {'options': {'title': 'a b'}}},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert _grants(db) == {('axb', ALICE, ADMIN), ('a_b', BOB, ADMIN)}


def test_transferring_a_b_makes_the_new_author_admin_of_a_b_only(db, app):
    _add_dashboard(db, 'axb', {ALICE: ADMIN})
    a_b = _add_dashboard(db, 'a_b', {BOB: ADMIN})

    response = _post(app, BOB, f'/dashboard/{a_b}/transfer/username', CAROL)

    assert response.status_code == 204, response.get_data(as_text=True)
    assert _grants(db) == {
        ('axb', ALICE, ADMIN),
        ('a_b', BOB, ADMIN),
        ('a_b', CAROL, ADMIN),
    }


def test_sharing_a_b_never_writes_on_axb(db, app):
    _add_dashboard(db, 'axb', {ALICE: ADMIN})
    a_b = _add_dashboard(db, 'a_b', {BOB: ADMIN})

    response = _share(app, BOB, a_b, {BOB: [ADMIN], CAROL: [VIEWER]}, {'ops': [VIEWER]})

    assert response.status_code == 204, response.get_data(as_text=True)
    assert _grants(db) == {
        ('axb', ALICE, ADMIN),
        ('a_b', BOB, ADMIN),
        ('a_b', CAROL, VIEWER),
        ('a_b', 'ops', VIEWER),
    }


def test_removing_the_group_shares_of_a_b_leaves_those_of_axb(db, app):
    _add_dashboard(db, 'axb', {ALICE: ADMIN}, {'ops': VIEWER})
    a_b = _add_dashboard(db, 'a_b', {BOB: ADMIN}, {'ops': VIEWER})

    response = _share(app, BOB, a_b, {BOB: [ADMIN]}, {})

    assert response.status_code == 204, response.get_data(as_text=True)
    assert _grants(db) == {
        ('axb', ALICE, ADMIN),
        ('axb', 'ops', VIEWER),
        ('a_b', BOB, ADMIN),
    }


def test_removing_the_share_of_john_doe_leaves_john_dot_doe(db, app):
    reports = _add_dashboard(
        db, 'reports', {BOB: ADMIN, JOHN_DOT_DOE: VIEWER, JOHN_DOE: VIEWER}
    )

    response = _share(app, BOB, reports, {BOB: [ADMIN], JOHN_DOT_DOE: [VIEWER]}, {})

    assert response.status_code == 204, response.get_data(as_text=True)
    assert _grants(db) == {
        ('reports', BOB, ADMIN),
        ('reports', JOHN_DOT_DOE, VIEWER),
    }


def test_alert_author_and_transfer_grants_land_on_the_alert_given(db):
    alerts = {
        name: Resource(resource_type_id=ALERT_TYPE, name=name, label=name)
        for name in ('axb', 'a_b')
    }
    db.session.add_all(alerts.values())
    db.session.commit()
    a_b_id = alerts['a_b'].id

    with Transaction() as transaction:
        a_b = transaction.find_by_id(Resource, a_b_id)
        bob = transaction.find_by_id(User, USER_IDS[BOB])
        carol = transaction.find_by_id(User, USER_IDS[CAROL])
        make_author_alert_administrator(transaction, a_b, bob)
        add_user_as_alert_administrator(transaction, a_b, carol)

    assert _grants(db) == {
        ('a_b', BOB, 'alert_admin'),
        ('a_b', CAROL, 'alert_admin'),
    }


def test_acls_resolved_by_resource_name_still_grant(db):
    _add_dashboard(db, 'reports', {BOB: ADMIN})
    viewer, _, reports = try_get_role_and_resource(VIEWER, 'DASHBOARD', 'reports')
    grants = [(viewer, reports)]

    replace_user_acls(db.session.query(User).get(USER_IDS[CAROL]), grants)
    replace_group_acls(db.session.query(Group).get(GROUP_IDS['ops']), grants)

    assert _grants(db) == {
        ('reports', BOB, ADMIN),
        ('reports', CAROL, VIEWER),
        ('reports', 'ops', VIEWER),
    }


def test_a_role_for_another_resource_type_is_refused(db):
    _add_dashboard(db, 'reports', {BOB: ADMIN})

    with pytest.raises(NotFound):
        try_get_role_and_resource('alert_admin', 'DASHBOARD', 'reports')
