"""Mint tokens the ways Harmony does, and see whom a request with one signs in."""

import json

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


def login(app, email):
    """The access token `/api2/authentication/login` returns."""
    login_route = AuthenticationResource.login_user_route.view_func
    with app.test_request_context('/api2/authentication/login?set_cookie=false'):
        response = login_route(None, email=email, password=PASSWORD, remember_me=False)
        return json.loads(response.get_data())['access_token']
