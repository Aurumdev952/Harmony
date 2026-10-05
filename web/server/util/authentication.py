from datetime import timedelta
from typing import TYPE_CHECKING, Optional
from flask import make_response, jsonify, current_app
from flask_jwt_extended import (
    create_access_token,
    get_jwt_claims,
    verify_jwt_in_request_optional,
)
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt import InvalidTokenError
from werkzeug.wrappers import Response

if TYPE_CHECKING:
    from models.alchemy.user import User

REMEMBER_ME_CLAIM = 'remember_me'
# The id of the account a browser session was issued to, so the session never
# signs in a later account that reuses the username.
USER_ID_CLAIM = 'user_id'


def create_user_access_token(
    user: 'User',
    expires_delta: Optional[timedelta] = None,
    remember_me: bool = False,
) -> str:
    if expires_delta is None:
        expires_delta = current_app.config['JWT_TOKEN_WEB_COOKIE_EXPIRATION']

    return create_access_token(
        identity=user.username,
        user_claims={
            'needs': ['*'],
            'query_needs': ['*'],
            REMEMBER_ME_CLAIM: remember_me,
            USER_ID_CLAIM: user.id,
        },
        expires_delta=expires_delta,
    )


def login_user(
    msg: str,
    user: 'User',
    remember_me: bool = False,
    expires: Optional[timedelta] = None,
) -> Response:
    if expires is None:
        expires = current_app.config['JWT_TOKEN_WEB_COOKIE_EXPIRATION']

    access_token = create_user_access_token(user, expires, remember_me)
    return create_auth_response(msg, access_token, remember_me, expires)


def create_auth_response(
    msg: str,
    access_token: str,
    remember_me: bool = False,
    expires: Optional[timedelta] = None,
) -> Response:
    if expires is None:
        expires = current_app.config['JWT_TOKEN_WEB_COOKIE_EXPIRATION']

    response = make_response(jsonify({"msg": msg}), 200)

    max_age = int(expires.total_seconds()) if remember_me else None

    response.set_cookie(
        current_app.config['JWT_ACCESS_COOKIE_NAME'],
        access_token,
        max_age=max_age,
        httponly=True,
    )

    return response


def is_session_persisted() -> bool:
    '''True when the request's token came from a "Remember me" login.

    Browsers never send a cookie's expiry back, so the choice is signed into the
    token. Reads the same token, header first, that authenticated the request.
    '''
    try:
        verify_jwt_in_request_optional()
    except (InvalidTokenError, JWTExtendedException):
        return False
    return bool(get_jwt_claims().get(REMEMBER_ME_CLAIM))
