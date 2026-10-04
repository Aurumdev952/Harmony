"""`POST /api2/user/<id>/generate_api_token` on a real Postgres (WP-2c finding F12).

The route returned a signed token without storing it, so the token authenticated only
after the admin app also PATCHed the user with it.
The admin app still saves the user with the token afterwards; that save must keep the
stored token rather than fail or duplicate it.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, decode_token
from flask_sqlalchemy import SQLAlchemy

import models.alchemy
from models.alchemy.api_token import APIToken
from models.alchemy.base import Base
from models.alchemy.user import User, UserStatus, UserStatusEnum
from web.server.routes.views.users import issue_api_token, update_user_api_tokens
from web.server.security.signal_handlers import check_token_validity

# User's relationships resolve only once every model is mapped, as in app_base.py.
for _module in pkgutil.iter_modules(models.alchemy.__path__):
    importlib.import_module(f'models.alchemy.{_module.name}')


@pytest.fixture(name='app')
def fixture_app(bare_flask_app, postgres_database: str) -> Iterator[Flask]:
    app = bare_flask_app()
    app.config.update(
        SQLALCHEMY_DATABASE_URI=postgres_database,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY='tests-web-placeholder-key',
    )
    db = SQLAlchemy(app, model_class=Base)
    JWTManager(app)
    with app.app_context():
        Base.metadata.create_all(
            db.engine,
            tables=[UserStatus.__table__, User.__table__, APIToken.__table__],
        )
        yield app
        db.session.remove()
        db.engine.dispose()


@pytest.fixture(name='user')
def fixture_user(app: Flask) -> User:
    session = app.extensions['sqlalchemy'].db.session
    session.add(UserStatus(id=1, status=UserStatusEnum.ACTIVE))
    # User.status is view-only, so the flush does not order the two inserts.
    session.commit()
    user = User(username='token-owner@harmony.invalid', status_id=1)
    session.add(user)
    session.commit()
    return user


def test_a_generated_api_token_authenticates_without_saving_the_user(user):
    token = issue_api_token(user)

    token_id = decode_token(token.token)['user_claims']['id']
    assert token_id == token.id
    assert check_token_validity(token_id)
    stored = APIToken.query.filter_by(id=token_id).one()
    assert (stored.user_id, stored.is_revoked) == (user.id, False)


class _Cache:
    """The app cache's memoize interface, which update_user_api_tokens clears."""

    def memoize(self):
        return lambda function: function

    def delete_memoized(self, function, *args):
        pass


def test_the_admin_apps_later_save_keeps_the_stored_token(app, user):
    app.cache = _Cache()
    token = issue_api_token(user)
    saved = {'$uri': f'/api2/api-token/{token.id}', 'id': token.id}

    update_user_api_tokens(user, [{**saved, 'is_revoked': False}])

    stored = APIToken.query.filter_by(user_id=user.id).all()
    assert [(row.id, row.is_revoked) for row in stored] == [(token.id, False)]
    assert check_token_validity(token.id)

    update_user_api_tokens(user, [{**saved, 'is_revoked': True}])

    assert not check_token_validity(token.id)
