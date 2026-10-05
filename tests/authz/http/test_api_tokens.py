'''API-token issue and revocation (contract C-5), as they behave with WP-2c merged.

`login_from_request` accepts a JWT that carries an `id` claim only while the
`api_token` row with that id exists and is not revoked (`api_token_user_id`,
read on every request since WP-0k; nothing is memoised).
`generate_api_token` stores the row as it issues the token (WP-2c F12,
`issue_api_token`), so the token authenticates at once; the admin app's later
save inserts with ON CONFLICT DO NOTHING and adds no second row. Only admin can
issue tokens today (it needs `change_password`, finding I3), so the admin
issues one for a provisioned user. Owner WP-5d.

Both kinds of JWT name their user by username alone. T1 and T2 pin, as today,
that a token issued to a deleted user signs in as whoever is later created with
the same username. Both flip in WP-0k.
'''

from __future__ import annotations

import json
import re

from tests.authz.http.stack import new_session, outcome

# Any signed-in user may list roles (sitewide view_resource); anonymous gets 401.
PROBE = '/api2/role'
# Every signed-in user gets this page, and it carries the signed-in user's id.
WHOAMI_PAGE = '/overview'
_BACKEND_JSON = re.compile(r'window\.__JSON_FROM_BACKEND = (.*?);\s*\n')


def _signed_in_as(stack, session) -> str:
    '''The URI of the user the page layout says is signed in, or the outcome
    of the page request when it is not the overview page.'''
    response = stack.request(session, 'GET', WHOAMI_PAGE)
    if outcome(response) != 'page:overviewPage':
        return outcome(response)
    user = json.loads(_BACKEND_JSON.search(response.text).group(1))['user']
    return f'/api2/user/{user["id"]}'


def _bearer(token: str):
    session = new_session()
    session.headers['Authorization'] = f'Bearer {token}'
    return session


def _save_tokens(stack, user_session, tokens) -> None:
    uri = user_session.user_uri
    user = stack.admin_json('GET', uri)
    stack.admin_json(
        'PATCH',
        uri,
        {
            '$uri': uri,
            'username': user['username'],
            'firstName': user['firstName'],
            'lastName': user['lastName'],
            'phoneNumber': user['phoneNumber'],
            'status': user['status'],
            'acls': [],
            'apiTokens': tokens,
            'roles': [role['$uri'] for role in user['roles']],
            'groups': [],
        },
    )


def _stored_tokens(stack, user_session) -> list:
    tokens = stack.admin_json('GET', user_session.user_uri)['apiTokens']
    return [(token['id'], token['isRevoked']) for token in tokens]


def test_api_token_authenticates_from_issue_until_revoked(stack):
    holder = stack.ensure_user('token-holder', [])
    issued = stack.admin_json('POST', f'{holder.user_uri}/generate_api_token')
    bearer = new_session()
    bearer.headers['Authorization'] = f'Bearer {issued["token"]}'
    saved = {'$uri': issued['$uri'], 'id': issued['id'], 'isRevoked': False}

    assert _stored_tokens(stack, holder) == [(issued['id'], False)]
    assert stack.request(bearer, 'GET', PROBE).status_code == 200

    _save_tokens(stack, holder, [saved])
    assert _stored_tokens(stack, holder) == [(issued['id'], False)]
    assert stack.request(bearer, 'GET', PROBE).status_code == 200

    _save_tokens(stack, holder, [{**saved, 'isRevoked': True}])
    assert stack.request(bearer, 'GET', PROBE).status_code == 401
    assert _stored_tokens(stack, holder) == [(issued['id'], True)]


def test_api_token_without_a_row_is_refused_for_a_recreated_username(stack):
    '''A token whose id has no api_token row gets 401, even though its identity
    (the username) resolves to a live user. Deleting the user cascades its token
    rows; recreating the username gives the old token a user but no row. The
    bearer is never used before the delete, so no memoised validity hides the
    missing row. This is the control for T1, where the token was used first.'''
    original = stack.ensure_user('token-orphan', [])
    issued = stack.admin_json('POST', f'{original.user_uri}/generate_api_token')
    stack.admin_json('DELETE', original.user_uri)

    recreated = stack.ensure_user('token-orphan', [])
    assert recreated.user_uri != original.user_uri
    assert _stored_tokens(stack, recreated) == []

    orphan = new_session()
    orphan.headers['Authorization'] = f'Bearer {issued["token"]}'
    assert stack.request(orphan, 'GET', PROBE).status_code == 401

    # Control: a token issued to the recreated user is accepted, so the 401
    # above comes from the missing row, not from the user or the signing key.
    fresh = stack.admin_json('POST', f'{recreated.user_uri}/generate_api_token')
    bearer = new_session()
    bearer.headers['Authorization'] = f'Bearer {fresh["token"]}'
    assert stack.request(bearer, 'GET', PROBE).status_code == 200


def test_used_api_token_of_a_deleted_user_signs_in_as_the_recreated_username(stack):
    '''T1: defect pinned as today; flips in WP-0k. An API token used before its
    user is deleted keeps authenticating, and signs in as the account later
    created with the same username. Holds while the token's validity stays
    cached: the Redis cache keeps it for 10 minutes and this test takes
    seconds.'''
    original = stack.ensure_user('token-reused', [])
    issued = stack.admin_json('POST', f'{original.user_uri}/generate_api_token')
    bearer = _bearer(issued['token'])
    assert _signed_in_as(stack, bearer) == original.user_uri

    stack.admin_json('DELETE', original.user_uri)
    recreated = stack.ensure_user('token-reused', [])
    assert recreated.user_uri != original.user_uri
    assert _stored_tokens(stack, recreated) == []

    assert stack.request(bearer, 'GET', PROBE).status_code == 200
    assert _signed_in_as(stack, bearer) == recreated.user_uri


def test_login_token_of_a_deleted_user_signs_in_as_the_recreated_username(stack):
    '''T2: defect pinned as today; flips in WP-0k. The access token from
    `POST /api2/authentication/login` (no cookie) carries no `id` claim and
    lives 365 days, so nothing is cached and nothing is checked but the
    username: after the user is deleted and the username recreated, the old
    token signs in as the new account.'''
    original = stack.ensure_user('login-reused', [])
    login = stack.request(
        new_session(),
        'POST',
        '/api2/authentication/login',
        {
            'email': original.headers['X-Username'],
            'password': original.headers['X-Password'],
            'remember_me': False,
        },
    )
    assert login.status_code == 200, login.text[:300]
    bearer = _bearer(login.json()['access_token'])
    assert _signed_in_as(stack, bearer) == original.user_uri

    stack.admin_json('DELETE', original.user_uri)
    recreated = stack.ensure_user('login-reused', [])
    assert recreated.user_uri != original.user_uri

    assert stack.request(bearer, 'GET', PROBE).status_code == 200
    assert _signed_in_as(stack, bearer) == recreated.user_uri
