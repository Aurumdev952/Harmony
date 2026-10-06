'''POST /api2/dashboard/<id>/transfer[/username] must move only that dashboard.

api_transfer_dashboard_ownership used to pass the dashboard where the bulk
helper expects the old author, so it moved every dashboard whose author_id
equalled the dashboard's id, and left the named dashboard where it was.
'''

import importlib
import os
import pkgutil

# config.settings reads these at import time; the transfer route never uses them.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-web-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')

# pylint: disable=wrong-import-position
import pytest
from flask import Flask, request_started
from flask_caching import Cache
from flask_login import LoginManager
from flask_potion import Api, ModelResource
from flask_principal import Principal, identity_loaded
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

import models.alchemy
from models.alchemy.dashboard import Dashboard
from models.alchemy.permission import (
    Permission,
    Resource,
    ResourceRole,
    ResourceType,
    ResourceTypeEnum,
)
from models.alchemy.user import User, UserAcl, UserStatus, UserStatusEnum
from web.server.api.dashboard_api_models import DashboardResource
from web.server.app_db import create_db
from web.server.configuration.settings import _populate_configuration_table
from web.server.security.signal_handlers import (
    initialize_request_logger,
    install_identity_loader,
    on_identity_loaded,
)

# User's relationships only configure once every model is registered.
for _module in pkgutil.iter_modules(models.alchemy.__path__):
    importlib.import_module(f'models.alchemy.{_module.name}')

DASHBOARD_TYPE = ResourceTypeEnum.DASHBOARD.value
# What the transfer route and the permission lookup read and write.
TABLES = (
    'configuration',
    'dashboard',
    'permission',
    'resource',
    'resource_role',
    'resource_role_permission',
    'resource_type',
    'role',
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

# Every dashboard id is also some other user's id: the bug keyed on that.
CAROL, BOB, ALICE = 1, 2, 3
BOB_DASHBOARD, ALICE_DASHBOARD, CAROL_DASHBOARD = 1, 2, 3
DASHBOARDS = {
    # dashboard id: (resource id, author id)
    BOB_DASHBOARD: (11, BOB),
    ALICE_DASHBOARD: (12, ALICE),
    CAROL_DASHBOARD: (13, CAROL),
}
USERNAMES = {
    CAROL: 'carol@example.org',
    BOB: 'bob@example.org',
    ALICE: 'alice@example.org',
}
# {dashboard id: (author id, ids of the users who are its dashboard_admin)}
INITIAL = {
    BOB_DASHBOARD: (BOB, {BOB}),
    ALICE_DASHBOARD: (ALICE, {ALICE}),
    CAROL_DASHBOARD: (CAROL, {CAROL}),
}


@compiles(JSONB, 'sqlite')
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return 'JSON'


# DashboardResource relates to the 'user' and 'resource' resources by name.
class UserStub(ModelResource):
    class Meta:
        name = 'user'
        model = User
        include_fields = ('username',)


class ResourceStub(ModelResource):
    class Meta:
        name = 'resource'
        model = Resource
        include_fields = ('name',)


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

    login_manager = LoginManager(app)
    login_manager.request_loader(
        lambda request: User.query.get(int(request.headers['X-Test-User-Id']))
    )
    install_identity_loader(Principal(app, use_sessions=False))
    identity_loaded.connect(on_identity_loaded, app)
    request_started.connect(initialize_request_logger, app)
    # Potion lets a resource join only one Api, hence the module scope.
    api = Api(app, prefix='/api2')
    api.add_resource(UserStub)
    api.add_resource(ResourceStub)
    api.add_resource(DashboardResource)

    with app.app_context():
        metadata = db.Model.metadata
        metadata.create_all(db.engine, tables=[metadata.tables[n] for n in TABLES])
        _seed_roles(db.session)
        yield app


def _seed_roles(session):
    _populate_configuration_table(session)
    session.add_all(UserStatus(id=s.value, status=s) for s in UserStatusEnum)
    session.add_all(ResourceType(id=t.value, name=t) for t in ResourceTypeEnum)
    view, edit, update_users = (
        Permission(resource_type_id=DASHBOARD_TYPE, permission=name)
        for name in ('view_resource', 'edit_resource', 'update_users')
    )
    session.add_all(
        [
            ResourceRole(
                name='dashboard_admin',
                resource_type_id=DASHBOARD_TYPE,
                permissions=[view, edit, update_users],
            ),
            ResourceRole(
                name='dashboard_viewer',
                resource_type_id=DASHBOARD_TYPE,
                permissions=[view],
            ),
        ]
    )
    session.commit()


@pytest.fixture(name='db', autouse=True)
def fixture_db(app):
    db = app.extensions['sqlalchemy'].db
    _seed_dashboards(db.session)
    yield db
    db.session.rollback()
    for model in (UserAcl, Dashboard, Resource, User):
        db.session.query(model).delete()
    db.session.commit()


def _seed_dashboards(session):
    session.add_all(
        User(id=user_id, username=username, status_id=UserStatusEnum.ACTIVE.value)
        for user_id, username in USERNAMES.items()
    )
    for dashboard_id, (resource_id, author_id) in DASHBOARDS.items():
        name = f'dashboard_{dashboard_id}'
        session.add(
            Resource(
                id=resource_id, resource_type_id=DASHBOARD_TYPE, name=name, label=name
            )
        )
        session.add(
            Dashboard(
                id=dashboard_id,
                slug=name,
                specification={},
                resource_id=resource_id,
                author_id=author_id,
                is_official=False,
                registered_users_can_download_data=False,
                unregistered_users_can_download_data=False,
            )
        )
        _grant(session, author_id, dashboard_id, 'dashboard_admin')
    session.commit()


def _grant(session, user_id, dashboard_id, role_name):
    role = session.query(ResourceRole).filter_by(name=role_name).one()
    resource_id = DASHBOARDS[dashboard_id][0]
    session.add(
        UserAcl(user_id=user_id, resource_id=resource_id, resource_role_id=role.id)
    )


def _transfer(app, caller_id, dashboard_id, new_author_id):
    resource_id = DASHBOARDS[dashboard_id][0]
    return app.test_client().post(
        f'/api2/dashboard/{resource_id}/transfer/username',
        json=USERNAMES[new_author_id],
        headers={'X-Test-User-Id': str(caller_id)},
    )


def _ownership(db):
    db.session.expire_all()
    admins = {}
    for acl in (
        db.session.query(UserAcl)
        .join(ResourceRole)
        .filter(ResourceRole.name == 'dashboard_admin')
    ):
        admins.setdefault(acl.resource_id, set()).add(acl.user_id)
    return {
        dashboard.id: (dashboard.author_id, admins.get(dashboard.resource_id, set()))
        for dashboard in db.session.query(Dashboard)
    }


def test_transfer_to_self_does_not_take_over_dashboard_of_user_with_matching_id(
    db, app
):
    response = _transfer(app, ALICE, ALICE_DASHBOARD, ALICE)

    assert response.status_code == 204
    assert _ownership(db) == INITIAL


def test_owner_transfers_own_dashboard_and_nothing_else(db, app):
    response = _transfer(app, ALICE, ALICE_DASHBOARD, CAROL)

    assert response.status_code == 204
    assert _ownership(db) == {**INITIAL, ALICE_DASHBOARD: (CAROL, {ALICE, CAROL})}


def test_caller_who_cannot_see_the_dashboard_gets_not_found(db, app):
    response = _transfer(app, ALICE, BOB_DASHBOARD, ALICE)

    assert response.status_code == 404
    assert _ownership(db) == INITIAL


def test_caller_without_update_users_on_the_dashboard_is_refused(db, app):
    _grant(db.session, ALICE, BOB_DASHBOARD, 'dashboard_viewer')
    db.session.commit()

    response = _transfer(app, ALICE, BOB_DASHBOARD, ALICE)

    assert response.status_code == 401
    assert _ownership(db) == INITIAL
