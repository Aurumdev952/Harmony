"""The real user lookups (JWT login, flask-user, invitations, role assignment)
on a SQLite `user` table, inside a Flask app wired as `web/server/app.py` wires
them: Flask-SQLAlchemy, flask-user's `UserManager` and the JWT request loader.
"""

import importlib
import logging
from datetime import timedelta
import os
from types import SimpleNamespace

import pytest
import sqlalchemy
from flask import Flask, g
from flask_jwt_extended import JWTManager

from config.loader import import_configuration_module
from models.alchemy.user import User
from tests.web.usernames.accounts import ACCOUNTS, ACCOUNTS_CREATED, PASSWORD, PENDING
from web.server.app_db import create_db
from web.server.configuration.flask import FlaskConfiguration
from web.server.database.setup import initialize_user_manager
from web.server.security.signal_handlers import install_login_manager_signal_handlers


# Every model module, as web/server/app_base.py imports them, so the mappers
# that `User` relates to can configure.
for _module in (
    'alerts',
    'api_token',
    'case_management',
    'configuration',
    'dashboard',
    'data_upload',
    'entity_matching',
    'feed',
    'permission',
    'pipeline_runs',
    'query',
    'query_policy',
    'security_group',
    'schedule',
    'user',
    'user_query_session',
):
    importlib.import_module(f'models.alchemy.{_module}')


def build_app(database_uri):
    """The app and its Flask-SQLAlchemy handle, with no tables."""
    here = os.path.dirname(__file__)
    app = Flask('tests.web.usernames', root_path=here, instance_path=here)
    app.config.update(
        TESTING=True,
        SECRET_KEY='tests-web-placeholder-session-key',
        SQLALCHEMY_DATABASE_URI=database_uri,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY='tests-web-placeholder-jwt-key',
        JWT_TOKEN_LOCATION=['headers', 'cookies'],
        JWT_ACCESS_COOKIE_NAME='accessKey',
        JWT_CSRF_METHODS=[],
        JWT_TOKEN_WEB_COOKIE_EXPIRATION=timedelta(days=1),
        WTF_CSRF_ENABLED=False,
        # flask-user registers the views production enables, at its URLs.
        **{
            name: value
            for name, value in vars(FlaskConfiguration()).items()
            if name.startswith('USER_')
        },
    )
    # Harmony's own reset page, which mailed reset links open.
    app.add_url_rule(
        '/user/reset-password', 'auth.reset_password', lambda: 'reset page'
    )
    db = create_db()
    db.init_app(app)
    JWTManager(app)
    app.zen_config = import_configuration_module('harmony_demo')
    app.user_authentication_router = SimpleNamespace(unauthorized=lambda: '')
    with app.app_context():
        initialize_user_manager(app, db)
        install_login_manager_signal_handlers(app, app.login_manager)
    return app, db


@pytest.fixture(name='app')
def fixture_app(tmp_path):
    app, db = build_app(f'sqlite:///{tmp_path}/users.db')
    with app.app_context():
        _create_users(db, app.user_manager.hash_password(PASSWORD))
    return app


# The user table and the empty tables a user edit reads its grants from.
TABLES = (
    'user',
    'role',
    'user_roles',
    'security_group',
    'security_group_users',
    'user_acl',
)


def _create_users(db, password_hash):
    with db.engine.begin() as connection:
        for table in TABLES:
            # Only the columns, so no foreign key needs the tables they point at.
            columns = ', '.join(
                '"id" INTEGER PRIMARY KEY'
                if column.name == 'id'
                else f'"{column.name}"'
                for column in User.metadata.tables[table].columns
            )
            connection.execute(sqlalchemy.text(f'CREATE TABLE "{table}" ({columns})'))
        connection.execute(
            sqlalchemy.text(
                'CREATE TABLE api_token (id PRIMARY KEY, user_id, is_revoked, '
                'created, last_modified)'
            )
        )
        for user_id, username, status, token in ACCOUNTS:
            connection.execute(
                sqlalchemy.text(
                    'INSERT INTO "user" (id, username, password, reset_password_token, '
                    'first_name, last_name, phone_number, status_id, created) '
                    "VALUES (:id, :username, :password, :token, 'First', 'Last', '', "
                    ':status, :created)'
                ),
                {
                    'id': user_id,
                    'username': username,
                    # Invitations create accounts with no password.
                    'password': '' if status == PENDING else password_hash,
                    'status': status,
                    'token': token,
                    'created': ACCOUNTS_CREATED,
                },
            )


@pytest.fixture(name='request_ctx')
def fixture_request_ctx(app):
    with app.test_request_context('/'):
        g.request_logger = logging.LoggerAdapter(logging.getLogger('tests.web'), {})
        yield
