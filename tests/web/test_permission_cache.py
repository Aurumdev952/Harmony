'''User.get_permissions must cache per account, never per username.

flask-caching keys a memoized method by its instance's __caching_id__, falling
back to repr(). User's repr is "<User object {username}>", so a username that
moved to another account (a rename, or a delete then a rename) carried the old
account's cached permissions with it until the entry expired.
'''

import importlib
import os
import pkgutil
import sys

import pytest
from flask import Flask
from flask_caching import Cache
from flask_caching.utils import get_id
from flask_principal import RoleNeed
from flask_user import SQLAlchemyAdapter, UserManager
from redis.exceptions import RedisError

import models.alchemy
import web.server.security.permissions
from log import LOG
from models.alchemy.permission import (
    Resource,
    ResourceRole,
    ResourceType,
    Role,
    SitewideResourceAcl,
)
from models.alchemy.security_group import Group, GroupUsers
from models.alchemy.user import User, UserAcl, UserRoles, UserStatus, UserStatusEnum
from web.server.app_db import create_db

BOSS = 'boss@example.org'
EVE = 'eve@example.org'
PASSWORD = 'eve-password'
ADMIN = {RoleNeed('admin')}

# User's relationships only configure once every model is registered.
for _module in pkgutil.iter_modules(models.alchemy.__path__):
    importlib.import_module(f'models.alchemy.{_module.name}')


@pytest.fixture(name='app', scope='module')
def fixture_app():
    here = os.path.dirname(__file__)
    app = Flask('tests.web', root_path=here, instance_path=here)
    app.config.update(
        SQLALCHEMY_DATABASE_URI='sqlite://',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY='tests-web-placeholder-key',
        WTF_CSRF_ENABLED=False,
        USER_ENABLE_EMAIL=False,
        USER_ENABLE_USERNAME=True,
        USER_ENABLE_CHANGE_USERNAME=True,
        USER_AFTER_CHANGE_USERNAME_ENDPOINT='user.login',
    )
    db = create_db()
    db.init_app(app)
    app.cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})
    # flask-user's own change-username view, as production mounts it.
    UserManager(
        SQLAlchemyAdapter(db, UserClass=User), app, username_validator=lambda *_: None
    )

    with app.app_context():
        # Every table these rows reference, for when SQLite enforces foreign
        # keys: web.server.database.setup turns that on once it is imported.
        models_used = [
            ResourceType,
            Resource,
            ResourceRole,
            UserStatus,
            User,
            Role,
            UserRoles,
            UserAcl,
            Group,
            GroupUsers,
            SitewideResourceAcl,
        ]
        db.Model.metadata.create_all(
            db.engine, tables=[model.__table__ for model in models_used]
        )
        # Deleting a user reads its API tokens. The model's timestamp defaults
        # only compile on PostgreSQL, so the table is declared by hand.
        db.session.execute(
            'CREATE TABLE api_token (id VARCHAR(10) PRIMARY KEY, user_id INTEGER, '
            'is_revoked BOOLEAN, created DATETIME, last_modified DATETIME)'
        )
        db.session.add_all(UserStatus(id=s.value, status=s) for s in UserStatusEnum)
        # SQLite rejects the 'false' server default, so set it.
        db.session.add(Role(name='admin', label='Site Admin', enable_data_export=False))
        db.session.commit()
        yield app


@pytest.fixture(autouse=True)
def fixture_clean_state(app, monkeypatch):
    # The public-dashboard check reads the configuration table. Every account
    # here is signed in, so it is always False.
    monkeypatch.setattr(
        web.server.security.permissions, 'is_public_dashboard_user', lambda: False
    )
    yield
    db = _db(app)
    db.session.rollback()
    db.session.query(UserRoles).delete()
    db.session.query(User).delete()
    db.session.commit()
    app.cache.clear()


def _db(app):
    return app.extensions['sqlalchemy'].db


def _load(app, user_id):
    '''Load the account the way the next request does: in a fresh session.'''
    db = _db(app)
    db.session.remove()
    return db.session.query(User).get(user_id)


def _add_user(app, username, admin=False, **columns):
    db = _db(app)
    user = User(
        username=username,
        password=app.user_manager.hash_password(PASSWORD),
        status_id=UserStatusEnum.ACTIVE.value,
        **columns,
    )
    if admin:
        user.roles = [db.session.query(Role).filter_by(name='admin').one()]
    db.session.add(user)
    db.session.commit()
    return user.id


def _permissions(app, user_id):
    return _load(app, user_id).get_permissions()


def _change_username_page(app, user_id, new_username):
    '''The account signs in on flask-user's form and renames itself on the
    /user/change-username page.
    '''
    client = app.test_client()
    response = client.post(
        '/user/sign-in',
        data={'username': _load(app, user_id).username, 'password': PASSWORD},
    )
    assert response.status_code == 302, response.get_data(as_text=True)
    response = client.post(
        '/user/change-username',
        data={'new_username': new_username, 'old_password': PASSWORD},
    )
    assert response.status_code == 302, response.get_data(as_text=True)
    assert _load(app, user_id).username == new_username


def _patch_username(app, user_id, new_username):
    '''What UserResource.update_user does to the account: the Potion manager
    sets the column and commits, then the route clears the account's cache.
    '''
    user = _load(app, user_id)
    user.username = new_username
    _db(app).session.commit()
    user.get_permissions.delete_memoized()


def _delete(app, user_id):
    '''What the Potion delete and force_delete_user do: session.delete.'''
    db = _db(app)
    db.session.delete(_load(app, user_id))
    db.session.commit()


def test_renamed_account_does_not_inherit_deleted_admins_permissions(app):
    # The WP-0k repro: boss signs in, an admin deletes boss, eve takes boss's
    # username on the change-username page and signs in again.
    boss = _add_user(app, BOSS, admin=True)
    eve = _add_user(app, EVE)
    assert _permissions(app, boss) == ADMIN

    _delete(app, boss)
    _change_username_page(app, eve, BOSS)

    assert _permissions(app, eve) == set()


def test_rename_on_change_username_page(app):
    boss = _add_user(app, BOSS, admin=True)
    assert _permissions(app, boss) == ADMIN

    _change_username_page(app, boss, 'boss-renamed@example.org')
    newcomer = _add_user(app, BOSS)

    assert _permissions(app, newcomer) == set()
    assert _permissions(app, boss) == ADMIN


def test_patch_rename(app):
    boss = _add_user(app, BOSS, admin=True)
    assert _permissions(app, boss) == ADMIN

    _patch_username(app, boss, 'boss-renamed@example.org')
    newcomer = _add_user(app, BOSS)

    assert _permissions(app, newcomer) == set()
    assert _permissions(app, boss) == ADMIN


def test_delete_clears_the_accounts_entry(app):
    boss = _add_user(app, BOSS, admin=True)
    assert _permissions(app, boss) == ADMIN

    _delete(app, boss)
    # Same username and the same id, as a restore or an id-reusing database
    # can give it. Only the delete hook keeps it from boss's entry.
    newcomer = _add_user(app, BOSS, id=boss)

    assert newcomer == boss
    assert _permissions(app, newcomer) == set()


def test_two_live_accounts_never_share_an_entry(app):
    boss = _add_user(app, BOSS, admin=True)
    eve = _add_user(app, EVE)

    assert _permissions(app, eve) == set()
    assert _permissions(app, boss) == ADMIN
    assert _permissions(app, eve) == set()
    assert get_id(_load(app, boss)) != get_id(_load(app, eve))


def _rename(app, user_id, new_username):
    user = _load(app, user_id)
    user.username = new_username
    _db(app).session.commit()


def test_rename_and_delete_in_an_app_without_a_cache(app, monkeypatch):
    # Scripts on util/local_script_wrapper.py and some test apps have an app
    # context but no app.cache.
    boss = _add_user(app, BOSS)

    with monkeypatch.context() as patch:
        patch.delattr(app, 'cache')
        _rename(app, boss, 'boss-renamed@example.org')
        _delete(app, boss)

    assert _load(app, boss) is None


def test_a_cache_outage_does_not_fail_the_rename_or_delete(app, monkeypatch):
    boss = _add_user(app, BOSS)
    # Nothing listens on port 1, so every cache call raises a ConnectionError.
    unreachable = Cache(
        config={'CACHE_TYPE': 'RedisCache', 'CACHE_REDIS_URL': 'redis://127.0.0.1:1/0'}
    )
    # Recorded at the call: how LOG's records reach caplog differs by branch.
    logged = []

    def record(message, *args, **_kwargs):
        logged.append((message % args, sys.exc_info()[0]))

    with monkeypatch.context() as patch:
        patch.setitem(app.extensions, 'cache', dict(app.extensions['cache']))
        unreachable.init_app(app)
        patch.setattr(app, 'cache', unreachable)
        patch.setattr(LOG, 'exception', record)
        _rename(app, boss, 'boss-renamed@example.org')
        _delete(app, boss)

    assert _load(app, boss) is None
    # Once for the rename, once for the delete, each inside the except block.
    message = f'Could not clear the cached permissions of user {boss}'
    assert [text for text, _ in logged] == [message, message]
    assert all(issubclass(error, RedisError) for _, error in logged)


def test_an_id_used_again_does_not_inherit_rights_cached_after_the_delete(
    app, monkeypatch
):
    boss = _add_user(app, BOSS, admin=True)
    _delete(app, boss)
    # A request that read boss between the delete's flush and its commit
    # caches boss's admin rights after the delete hook has cleared them.
    with monkeypatch.context() as patch:
        patch.setattr(User, 'enumerate_permissions', lambda _user, _txn: iter(ADMIN))
        assert User(id=boss).get_permissions() == ADMIN

    newcomer = _add_user(app, EVE, id=boss)

    assert newcomer == boss
    assert _permissions(app, newcomer) == set()


def test_a_rename_outside_the_orm_does_not_move_cached_rights(app):
    # Bulk updates, SQL and Hasura skip the ORM hooks, so only the id key
    # keeps eve from reading boss's entry here.
    boss = _add_user(app, BOSS, admin=True)
    eve = _add_user(app, EVE)
    assert _permissions(app, boss) == ADMIN
    db = _db(app)
    table = User.__table__
    db.session.execute(
        table.update().where(table.c.id == boss).values(username='boss-renamed@example.org')
    )
    db.session.execute(table.update().where(table.c.id == eve).values(username=BOSS))
    db.session.commit()

    assert _permissions(app, eve) == set()
