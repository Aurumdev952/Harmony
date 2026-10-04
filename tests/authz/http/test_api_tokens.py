'''API-token issue and revocation (contract C-5), as they behave on main.

`login_from_request` accepts a JWT that carries an `id` claim only while the
`api_token` row with that id exists and is not revoked (`check_token_validity`,
memoised; `update_user_api_tokens` clears the memo when it saves or revokes).
`generate_api_token` returns a signed token but writes no row: the frontend
saves it with the next user PATCH. Only admin can issue tokens today (it needs
`change_password`, finding I3), so the admin issues one for a provisioned user.
Owner WP-5d.
'''

from __future__ import annotations

from tests.authz.http.stack import new_session

# Any signed-in user may list roles (sitewide view_resource); anonymous gets 401.
PROBE = '/api2/role'


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


def test_api_token_authenticates_only_while_saved_and_not_revoked(stack):
    holder = stack.ensure_user('token-holder', [])
    issued = stack.admin_json('POST', f'{holder.user_uri}/generate_api_token')
    bearer = new_session()
    bearer.headers['Authorization'] = f'Bearer {issued["token"]}'
    saved = {'$uri': issued['$uri'], 'id': issued['id'], 'isRevoked': False}

    assert stack.request(bearer, 'GET', PROBE).status_code == 401

    _save_tokens(stack, holder, [saved])
    assert stack.request(bearer, 'GET', PROBE).status_code == 200

    _save_tokens(stack, holder, [{**saved, 'isRevoked': True}])
    assert stack.request(bearer, 'GET', PROBE).status_code == 401
    (token,) = stack.admin_json('GET', holder.user_uri)['apiTokens']
    assert (token['id'], token['isRevoked']) == (issued['id'], True)
