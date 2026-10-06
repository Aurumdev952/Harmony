"""Mint tokens the ways Harmony does, and see whom a request with one signs in."""

import json

import sqlalchemy

from flask_jwt_extended import create_access_token
from flask_login import current_user

from tests.web.usernames.accounts import PASSWORD
from web.server.api.authentication_api_models import AuthenticationResource


def signed_in_id(app, token):
    with app.test_request_context('/', headers={'Authorization': f'Bearer {token}'}):
        return current_user.id if current_user.is_authenticated else None


def session_token_without_account_id(app, identity):
    """A browser session as minted before WP-0k: the username the user typed."""
    with app.test_request_context('/'):
        return create_access_token(
            identity=identity,
            user_claims={'needs': ['*'], 'query_needs': ['*'], 'remember_me': False},
        )


def api_token(app, identity, token_id):
    """An API token as `APIToken.generate_token` mints it."""
    with app.test_request_context('/'):
        return create_access_token(
            identity=identity,
            user_claims={'id': token_id, 'needs': ['*'], 'query_needs': ['*']},
        )


def login(app, email, password=PASSWORD):
    """The access token `/api2/authentication/login` returns."""
    login_route = AuthenticationResource.login_user_route.view_func
    with app.test_request_context('/api2/authentication/login?set_cookie=false'):
        response = login_route(None, email=email, password=password, remember_me=False)
        return json.loads(response.get_data())['access_token']


def mailed_reset_token(app, user_id):
    """A reset token as a reset or invitation mail carries it: generated for the
    account and stored as its `reset_password_token`."""
    with app.test_request_context('/'):
        token = app.user_manager.generate_token(user_id)
    with app.app_context():
        engine = app.extensions['sqlalchemy'].db.engine
        with engine.begin() as connection:
            connection.execute(
                sqlalchemy.text(
                    'UPDATE "user" SET reset_password_token = :token WHERE id = :id'
                ),
                {'token': token, 'id': user_id},
            )
    return token


def complete_reset(app, token, password):
    """`POST /api2/authentication/reset_password`."""
    reset = AuthenticationResource.reset_password.view_func
    with app.test_request_context('/api2/authentication/reset_password', method='POST'):
        return reset(None, token=token, password=password)
