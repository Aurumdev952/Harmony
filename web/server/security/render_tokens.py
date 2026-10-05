'''Tokens that sign the renderer's browser in for one dashboard render (SEC-7).

A render token is an `accessKey` JWT for one account that grants `view_resource`
on one dashboard and whatever query policy that account holds. It names the
account by id (`user_id`), as WP-0k's sessions do. Its `render` claim names a
registration in the app cache that exists only while the render that minted it
runs, so the token is refused as soon as the render returns. Its optional
`policy` claim is the digest of the policy the render was requested under; the
token grants nothing once the account's digest differs.
'''

import secrets
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Iterator, Mapping, Optional, Protocol

from flask import current_app
from flask_jwt_extended import create_access_token, get_jwt_claims

from web.server.util.authentication import USER_ID_CLAIM

RENDER_CLAIM = 'render'
RENDER_POLICY_CLAIM = 'policy'

# Dashboard render tokens keep whatever query policy the account they are issued
# for holds.
RENDER_TOKEN_QUERY_NEEDS = ['*']


class Account(Protocol):
    id: int
    username: str


def _registration_key(render_id: str) -> str:
    return f'render-token:{render_id}'


@contextmanager
def render_token(
    account: Account,
    resource_id: int,
    *,
    policy: Optional[str],
    ttl_seconds: int,
) -> Iterator[str]:
    render_id = secrets.token_urlsafe(32)
    key = _registration_key(render_id)
    claims = {
        'needs': [['view_resource', resource_id, 'dashboard']],
        'query_needs': RENDER_TOKEN_QUERY_NEEDS,
        RENDER_CLAIM: render_id,
        USER_ID_CLAIM: account.id,
    }
    if policy is not None:
        claims[RENDER_POLICY_CLAIM] = policy
    current_app.cache.set(key, True, timeout=ttl_seconds)
    try:
        yield create_access_token(
            identity=account.username,
            expires_delta=timedelta(seconds=ttl_seconds),
            user_claims=claims,
        )
    finally:
        current_app.cache.delete(key)


def is_render_token_live(render_id) -> bool:
    return isinstance(render_id, str) and bool(
        current_app.cache.get(_registration_key(render_id))
    )


def is_spent_render_token(claims: Mapping[str, Any]) -> bool:
    '''Whether `claims` are a render token's whose render has returned. Such a
    token signs nobody in, which keeps it single-use (SEC-7).'''
    return RENDER_CLAIM in claims and not is_render_token_live(claims[RENDER_CLAIM])


def is_render_request() -> bool:
    '''Whether the current request is signed in with a live render token.'''
    return is_render_token_live(get_jwt_claims().get(RENDER_CLAIM))
