'''The real Flask app with its Potion routes, Flask-Principal and header login,
over a disposable PostgreSQL holding the seeded roles these tests need.

Set HARMONY_TEST_DATABASE_URL to use an existing empty database; otherwise a
throwaway postgres container is started on a free loopback port.
'''

from __future__ import annotations

import os
import subprocess
import time
import uuid
from types import SimpleNamespace
from unittest import mock

import pytest

# config/settings.py and the config loader read these at import time; the values are
# test-only placeholders, and harmony_demo is the deployment checked into the repo.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-web-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('ZEN_ENV', 'harmony_demo')

_POSTGRES_IMAGE = 'postgres:15.2-alpine'
_PASSWORD = 'escalation-test-password'

_DASHBOARD_ADMIN = [
    'create_resource',
    'delete_resource',
    'edit_resource',
    'update_users',
    'view_resource',
]

# Resource roles and roles as the harmony_demo migrations seed them
# (tests/authz/seed.yaml on the WP-2b branch), limited to what these tests use.
RESOURCE_ROLES = {
    'dashboard_viewer': ('DASHBOARD', ['view_resource']),
    'dashboard_admin': ('DASHBOARD', _DASHBOARD_ADMIN),
    'alert_admin': ('ALERT', _DASHBOARD_ADMIN),
}
ROLES = {
    'admin': {},
    'dashboard_admin': {'dashboard': 'dashboard_admin'},
    'manager': {
        'SITE': [
            'delete_user',
            'edit_user',
            'invite_user',
            'list_resources',
            'list_roles',
            'list_users',
            'reset_password',
            'view_admin_page',
            'view_user',
        ]
    },
    'user_admin': {
        'USER': [
            'create_resource',
            'delete_resource',
            'edit_resource',
            'invite_user',
            'reset_password',
            'update_roles',
            'view_resource',
        ]
    },
    'group_admin': {
        'GROUP': [
            'create_resource',
            'delete_resource',
            'edit_resource',
            'update_roles',
            'update_users',
            'view_resource',
        ]
    },
    'group_moderator': {'GROUP': ['edit_resource', 'update_users', 'view_resource']},
    'role_administrator': {
        'ROLE': ['create_resource', 'delete_resource', 'edit_resource', 'view_resource']
    },
    'role_moderator': {'ROLE': ['edit_resource', 'view_resource']},
    # Not seeded: one query policy, data export, and ROLE update_permissions
    # (which no seeded role holds), each on its own.
    'all_sources_reader': {'query_policies': [('source', None)]},
    'exporter': {'export': True},
    'permission_editor': {'ROLE': ['update_permissions']},
    # Creates dashboards without holding any role on existing ones, as the
    # seeded `_default_role` does.
    'dashboard_creator': {'DASHBOARD': ['create_resource']},
}
QUERY_POLICIES = [('source', None), ('StateName', 'Kigali')]


def _docker(*args: str) -> str:
    return subprocess.run(
        ['docker', *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture(name='database_url', scope='session')
def fixture_database_url():
    url = os.environ.get('HARMONY_TEST_DATABASE_URL')
    if url:
        yield url
        return

    name = f'harmony-wp0h-test-{uuid.uuid4().hex[:8]}'
    _docker(
        'run',
        '--rm',
        '-d',
        '--name',
        name,
        '-e',
        f'POSTGRES_PASSWORD={_PASSWORD}',
        '-p',
        '127.0.0.1::5432',
        _POSTGRES_IMAGE,
    )
    try:
        port = _docker('port', name, '5432/tcp').splitlines()[0].rsplit(':', 1)[1]
        deadline = time.monotonic() + 60
        while subprocess.run(
            ['docker', 'exec', name, 'pg_isready', '-U', 'postgres', '-h', '127.0.0.1'],
            capture_output=True,
            check=False,
        ).returncode:
            if time.monotonic() > deadline:
                raise RuntimeError(f'{name} did not become ready')
            time.sleep(0.5)
        yield f'postgresql://postgres:{_PASSWORD}@127.0.0.1:{port}/postgres'
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, check=False)


def _seed(session) -> None:
    # pylint: disable=import-outside-toplevel
    from models.alchemy.permission import (
        Permission,
        ResourceRole,
        ResourceType,
        ResourceTypeEnum,
        Role,
    )
    from models.alchemy.query_policy import (
        QueryPolicy,
        QueryPolicyType,
        QueryPolicyTypeEnum,
    )
    from models.alchemy.user import UserStatus, UserStatusEnum
    from web.server.configuration.settings import _populate_configuration_table

    session.add_all(UserStatus(id=e.value, status=e) for e in UserStatusEnum)
    session.add_all(ResourceType(id=e.value, name=e) for e in ResourceTypeEnum)
    session.add_all(QueryPolicyType(id=e.value, name=e) for e in QueryPolicyTypeEnum)
    session.flush()

    permissions = {}

    def permission(type_name: str, name: str) -> Permission:
        key = (type_name, name)
        if key not in permissions:
            permissions[key] = Permission(
                resource_type_id=ResourceTypeEnum[type_name].value, permission=name
            )
            session.add(permissions[key])
        return permissions[key]

    resource_roles = {
        name: ResourceRole(
            name=name,
            resource_type_id=ResourceTypeEnum[type_name].value,
            permissions=[permission(type_name, p) for p in perms],
        )
        for name, (type_name, perms) in RESOURCE_ROLES.items()
    }
    session.add_all(resource_roles.values())
    permission('SITE', 'view_admin_page')
    policies = {
        key: QueryPolicy(
            dimension=key[0],
            dimension_value=key[1],
            query_policy_type_id=QueryPolicyTypeEnum.DIMENSION.value,
        )
        for key in QUERY_POLICIES
    }
    session.add_all(policies.values())
    session.flush()

    for name, spec in ROLES.items():
        session.add(
            Role(
                name=name,
                label=name,
                permissions=[
                    permission(type_name, p)
                    for type_name in ('SITE', 'USER', 'GROUP', 'ROLE', 'DASHBOARD')
                    for p in spec.get(type_name, [])
                ],
                query_policies=[
                    policies[key] for key in spec.get('query_policies', [])
                ],
                enable_data_export=spec.get('export', False),
                dashboard_resource_role_id=(
                    resource_roles[spec['dashboard']].id
                    if 'dashboard' in spec
                    else None
                ),
            )
        )
    session.commit()
    _populate_configuration_table(session)


@pytest.fixture(name='app', scope='session')
def fixture_app(database_url):
    # pylint: disable=import-outside-toplevel
    from flask_caching import Cache
    from flask_jwt_extended import JWTManager

    from web.server.app import _register_potion_routes, _register_principals
    from web.server.app_base import create_app_base, initialize_zenysis_module
    from web.server.configuration.flask import FlaskConfiguration
    from web.server.database.setup import initialize_user_manager

    config = FlaskConfiguration()
    config.SQLALCHEMY_DATABASE_URI = database_url
    config.TESTING = True
    app, db = create_app_base(config)
    initialize_zenysis_module(app)
    app.cache = Cache(app, config={'CACHE_TYPE': 'null', 'CACHE_NO_NULL_WARNING': True})
    app.user_authentication_router = SimpleNamespace(
        unauthorized=lambda: ('unauthorized', 403)
    )
    with app.app_context():
        db.drop_all()
        db.create_all()
        _seed(db.session)
        initialize_user_manager(app, db)
        JWTManager(app)
        _register_principals(app)
        # Query resources load dimension values from Druid; none of them is under test.
        with mock.patch(
            'web.server.api.api_models.list_query_resource_types', return_value=[]
        ):
            _register_potion_routes(app)
    return app


class Actor(SimpleNamespace):
    def request(self, method: str, path: str, body=None):
        headers = (
            {}
            if self.browser
            else {'X-Username': self.username, 'X-Password': _PASSWORD}
        )
        return self.client.open(path, method=method, json=body, headers=headers)


@pytest.fixture(name='make_user')
def fixture_make_user(app):
    # pylint: disable=import-outside-toplevel
    from models.alchemy.permission import Role
    from models.alchemy.security_group import Group
    from models.alchemy.user import User, UserStatusEnum
    from web.server.util.authentication import create_user_access_token

    db = app.extensions['sqlalchemy'].db

    def make_user(roles=(), groups=(), browser=False, username=None) -> Actor:
        '''`browser` signs in with the `accessKey` JWT cookie the login page sets,
        instead of the X-Username and X-Password headers.
        '''
        with app.app_context():
            username = username or f'{uuid.uuid4().hex[:10]}@escalation.test'
            user = User(
                username=username,
                password=app.user_manager.hash_password(_PASSWORD),
                first_name='Escalation',
                last_name='Test',
                status_id=UserStatusEnum.ACTIVE.value,
                roles=[db.session.query(Role).filter_by(name=r).one() for r in roles],
                groups=db.session.query(Group).filter(Group.name.in_(groups)).all(),
            )
            db.session.add(user)
            db.session.commit()
            client = app.test_client()
            if browser:
                with app.test_request_context():
                    token = create_user_access_token(username)
                client.set_cookie('localhost', 'accessKey', token)
            return Actor(id=user.id, username=username, client=client, browser=browser)

    return make_user
