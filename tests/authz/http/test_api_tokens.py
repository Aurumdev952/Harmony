'''Which account a token signs in (contract C-5), as WP-0k binds tokens to accounts.

Three kinds of JWT reach `login_from_request`: API tokens (an `id` claim naming
their `api_token` row), sessions from `POST /api2/authentication/login` and
registration, and render tokens. `account_for_token` (WP-0k) takes the account
id from the token's `api_token` row (read on every request), else from its
`user_id` claim, else, for a session minted before WP-0k, from the one account
its username can mean that is not a pending invitation. The account must be
active, have exactly the username the token names, and not have been created
in a later second than the token was issued.

Before WP-0k (integration bc5cb2d) every token named its account by username
alone, looked up with ILIKE and `first()`, and an API token's validity was
memoised in Redis for 10 minutes. `generate_api_token` stores the row as it
issues the token (WP-2c F12), so the token authenticates at once. Only admin
can issue tokens today (it needs `change_password`, finding I3), so the admin
issues one for a provisioned user. Owner WP-5d.

T1 and T2 pinned that a token of a deleted user signed in as whoever later took
the username; WP-0k flipped them (INV-3 rows T-2 and T-1). The pre-WP-0k
session pins are INV-3 rows T-3, T-5, T-6 and U-4; WP-0k reissues no session, so
those tokens stay in browsers for up to 365 days after deploy.
'''

from __future__ import annotations

import secrets
import time

import pytest

from tests.authz.http.stack import (
    PENDING,
    USER_DOMAIN,
    bearer,
    mint_token,
    new_session,
)

pytestmark = pytest.mark.usefixtures('own_accounts')

# Any signed-in user may list roles (sitewide view_resource); anonymous gets 401.
PROBE = '/api2/role'
# The claims a browser session carried before WP-0k: no `user_id`.
PRE_WP0K_SESSION_CLAIMS = {'needs': ['*'], 'query_needs': ['*'], 'remember_me': False}


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


def _delete(stack, uri) -> None:
    stack.admin_json('DELETE', uri)
    stack.created_users.discard(uri)


def _pre_wp0k_session(username: str) -> str:
    return mint_token(username, PRE_WP0K_SESSION_CLAIMS)


def test_api_token_authenticates_from_issue_until_revoked(stack):
    holder = stack.ensure_user('token-holder', [])
    issued = stack.admin_json('POST', f'{holder.user_uri}/generate_api_token')
    bearer_session = bearer(issued['token'])
    saved = {'$uri': issued['$uri'], 'id': issued['id'], 'isRevoked': False}

    assert _stored_tokens(stack, holder) == [(issued['id'], False)]
    assert stack.request(bearer_session, 'GET', PROBE).status_code == 200

    _save_tokens(stack, holder, [saved])
    assert _stored_tokens(stack, holder) == [(issued['id'], False)]
    assert stack.request(bearer_session, 'GET', PROBE).status_code == 200

    _save_tokens(stack, holder, [{**saved, 'isRevoked': True}])
    assert stack.request(bearer_session, 'GET', PROBE).status_code == 401
    assert _stored_tokens(stack, holder) == [(issued['id'], True)]


def test_api_token_without_a_row_is_refused_for_a_recreated_username(stack):
    '''A token whose id has no api_token row gets 401, even though its identity
    (the username) resolves to a live user. Deleting the user cascades its token
    rows; recreating the username gives the old token a user but no row. The
    bearer is never used before the delete, so before WP-0k no memoised validity
    hid the missing row either: this control holds before and after WP-0k.'''
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
    fresh_bearer = new_session()
    fresh_bearer.headers['Authorization'] = f'Bearer {fresh["token"]}'
    assert stack.request(fresh_bearer, 'GET', PROBE).status_code == 200


def test_used_api_token_of_a_deleted_user_signs_in_nobody(stack):
    '''T1, flipped by WP-0k (INV-3 row T-2). An API token used before its user
    is deleted, then presented after the username is recreated.
    Before WP-0k: 200, signed in as the recreated account, while the token's
    validity stayed in the 10-minute Redis memo (this test takes seconds).
    After: 401 and anonymous. The loader reads the token's row on every
    request, and the delete cascaded it.'''
    original = stack.ensure_user('token-reused', [])
    issued = stack.admin_json('POST', f'{original.user_uri}/generate_api_token')
    used = bearer(issued['token'])
    assert stack.signed_in_as(used) == original.user_uri

    stack.admin_json('DELETE', original.user_uri)
    recreated = stack.ensure_user('token-reused', [])
    assert recreated.user_uri != original.user_uri
    assert _stored_tokens(stack, recreated) == []

    assert stack.request(used, 'GET', PROBE).status_code == 401
    assert stack.signed_in_as(used) == 'login'


def test_login_token_of_a_deleted_user_signs_in_nobody(stack):
    '''T2, flipped by WP-0k (INV-3 row T-1). The access token from
    `POST /api2/authentication/login` (no cookie) lives 365 days.
    Before WP-0k: it named only the username, so after the user was deleted
    and the username recreated it signed in as the new account (200).
    After: it carries the account id (`user_id`), and the recreated account
    has another id, so 401 and anonymous.'''
    original = stack.ensure_user('login-reused', [])
    _, login = stack.login(
        original.headers['X-Username'], original.headers['X-Password']
    )
    assert login.status_code == 200, login.text[:300]
    token_session = bearer(login.json()['access_token'])
    assert stack.signed_in_as(token_session) == original.user_uri

    stack.admin_json('DELETE', original.user_uri)
    recreated = stack.ensure_user('login-reused', [])
    assert recreated.user_uri != original.user_uri

    assert stack.request(token_session, 'GET', PROBE).status_code == 401
    assert stack.signed_in_as(token_session) == 'login'


def test_login_token_does_not_follow_its_username_to_another_account(stack):
    '''WP-0k INV-3 row T-1, the rename case. A session's account is renamed
    and a new account takes the old username.
    Before WP-0k: the session signed in the new account.
    After: anonymous. The session names the first account by id, and that
    account no longer has the username the session names (row T-4).'''
    username = f'session-renamed@{USER_DOMAIN}'
    password = secrets.token_urlsafe(18)
    original = stack.create_account(username, password)
    _, login = stack.login(username, password)
    assert login.status_code == 200, login.text[:300]
    token_session = bearer(login.json()['access_token'])
    assert stack.signed_in_as(token_session) == original

    renamed = stack.patch_user(original, username=f'session-renamed-away@{USER_DOMAIN}')
    assert renamed.status_code == 200, renamed.text[:300]
    successor = stack.create_account(username, secrets.token_urlsafe(18))

    assert stack.signed_in_as(token_session) == 'login'
    assert successor != original


def test_session_minted_before_wp0k_signs_in_its_account_in_any_case(stack):
    '''Control, the same before and after WP-0k (C-5 rule 1, last branch). A
    session minted before WP-0k names the username as the user typed it, in
    any case, and signs in the one account equal to it ignoring case.'''
    username = f'legacy.one@{USER_DOMAIN}'
    account = stack.create_account(username, secrets.token_urlsafe(18))

    for typed in (username, f'LEGACY.ONE@{USER_DOMAIN}', f'Legacy.One@{USER_DOMAIN}'):
        assert stack.signed_in_as(bearer(_pre_wp0k_session(typed))) == account, typed


def test_session_minted_before_wp0k_signs_in_the_registered_account_not_a_pending_twin(
    stack,
):
    '''WP-0k INV-3 rows U-4 and T-6. A registered `legacy.twin@` and a pending
    invitation `Legacy.Twin@` (made by the case-blind invitations before WP-0k)
    with no password, as an invitation that never registered has (with one,
    it counts as an account that could sign in, and row T-5 signs in nobody).
    Before WP-0k: ILIKE with `first()` and no ORDER BY gave whichever row the
    table scan met first, which can be the pending account (here it is: the
    shell's row is written first).
    After: the one account that is not pending, for every spelling.'''
    shell = stack.create_account(
        f'legacy.twin-shell@{USER_DOMAIN}', secrets.token_urlsafe(18)
    )
    account = stack.create_account(
        f'legacy.twin-account@{USER_DOMAIN}', secrets.token_urlsafe(18)
    )
    # Written last, the registered account's row follows the shell's in the
    # table; `POST /api2/user` refuses a case twin of the pending shell.
    stack.rewrite_account(shell, f'Legacy.Twin@{USER_DOMAIN}', PENDING)
    stack.clear_password(shell)
    stack.rewrite_account(account, f'legacy.twin@{USER_DOMAIN}')

    for typed in (
        f'legacy.twin@{USER_DOMAIN}',
        f'LEGACY.TWIN@{USER_DOMAIN}',
        f'Legacy.Twin@{USER_DOMAIN}',
    ):
        signed_in = stack.signed_in_as(bearer(_pre_wp0k_session(typed)))
        assert signed_in == account, (typed, signed_in, 'pending shell:', shell)


def test_session_minted_before_wp0k_for_a_case_only_pair_signs_in_nobody(stack):
    '''WP-0k INV-3 row T-5. Two registered accounts equal ignoring case (made
    before WP-0k refused case twins; here written directly in the database).
    Before WP-0k: a session naming either spelling signed in whichever account
    ILIKE with `first()` returned, not necessarily the one that signed in.
    After: that username can mean either account, so nobody.'''
    first = stack.create_account(
        f'legacy.pair@{USER_DOMAIN}', secrets.token_urlsafe(18)
    )
    second = stack.create_account(
        f'legacy.pair-twin@{USER_DOMAIN}', secrets.token_urlsafe(18)
    )
    stack.rewrite_account(second, f'Legacy.Pair@{USER_DOMAIN}')

    for typed in (
        f'legacy.pair@{USER_DOMAIN}',
        f'Legacy.Pair@{USER_DOMAIN}',
        f'LEGACY.PAIR@{USER_DOMAIN}',
    ):
        assert stack.signed_in_as(bearer(_pre_wp0k_session(typed))) == 'login', (
            typed,
            first,
            second,
        )


def test_session_minted_before_wp0k_naming_a_pattern_of_two_accounts_signs_in_nobody(
    stack,
):
    '''WP-0k INV-3 row T-5, the pattern case (5283c7b). Before WP-0k sign-in
    matched the typed string as an ILIKE pattern, so typing `legacy_pattern@`
    with the password of `legacy.pattern@` made a session naming
    `legacy_pattern@`. With a `legacy_pattern@` account also present:
    Before WP-0k: that session signed in `legacy.pattern@`, the first match.
    After: the pattern matches two accounts, so nobody; a session naming
    `legacy.pattern@`, which matches one, signs it in.'''
    older = stack.create_account(
        f'legacy.pattern@{USER_DOMAIN}', secrets.token_urlsafe(18)
    )
    stack.create_account(f'legacy_pattern@{USER_DOMAIN}', secrets.token_urlsafe(18))

    typed = bearer(_pre_wp0k_session(f'legacy_pattern@{USER_DOMAIN}'))
    assert stack.signed_in_as(typed) == 'login'
    exact = bearer(_pre_wp0k_session(f'legacy.pattern@{USER_DOMAIN}'))
    assert stack.signed_in_as(exact) == older


def test_session_minted_before_wp0k_never_signs_in_a_pending_account(stack):
    '''WP-0k INV-3 row T-6. The only account equal to the session's username
    is a pending invitation.
    Before WP-0k: the session signed in the pending account.
    After: anonymous; a pending account never signed in.'''
    shell = stack.create_account(
        f'legacy-pending@{USER_DOMAIN}', secrets.token_urlsafe(18)
    )
    stack.rewrite_account(shell, f'legacy-pending@{USER_DOMAIN}', PENDING)

    assert (
        stack.signed_in_as(bearer(_pre_wp0k_session(f'legacy-pending@{USER_DOMAIN}')))
        == 'login'
    )


def test_session_minted_before_wp0k_does_not_sign_in_an_account_created_after_it(
    stack,
):
    '''WP-0k INV-3 row T-3. A session minted the pre-WP-0k way, then its
    account is deleted and the username recreated in a later second.
    Before WP-0k: it signed in the recreated account.
    After: anonymous, because the account was created after the token's `iat`.
    Controls: the token signs in the original account, and a session minted
    the same way after the recreate signs in the new one.'''
    username = f'legacy-recreated@{USER_DOMAIN}'
    original = stack.create_account(username, secrets.token_urlsafe(18))
    token = _pre_wp0k_session(username)
    assert stack.signed_in_as(bearer(token)) == original

    time.sleep(1.1)  # `iat` and `created` compare to the second.
    _delete(stack, original)
    recreated = stack.create_account(username, secrets.token_urlsafe(18))
    assert recreated != original

    assert stack.signed_in_as(bearer(token)) == 'login'
    assert stack.signed_in_as(bearer(_pre_wp0k_session(username))) == recreated


def test_session_minted_before_wp0k_without_iat_signs_in_nobody(stack):
    '''WP-0k C-5 rule 2: a token with no `iat` signs in nobody, since nothing
    says when it was issued.
    Before WP-0k: a session naming the username signed it in, `iat` or not.
    After: anonymous. Control: the same session with an `iat` signs it in.'''
    username = f'legacy-no-iat@{USER_DOMAIN}'
    account = stack.create_account(username, secrets.token_urlsafe(18))

    no_iat = mint_token(username, PRE_WP0K_SESSION_CLAIMS, with_iat=False)
    assert stack.signed_in_as(bearer(no_iat)) == 'login'
    assert stack.signed_in_as(bearer(_pre_wp0k_session(username))) == account


def test_a_case_only_rename_ends_the_accounts_session_and_api_token(stack):
    '''WP-0k INV-3 row T-4. An account's username changes case only
    (`case.rename@` to `Case.Rename@`).
    Before WP-0k: its session and API token, looked up with ILIKE, kept
    signing it in.
    After: both are anonymous; they name the exact old username. Control: a
    login with the new spelling signs the account in.'''
    username, password = f'case.rename@{USER_DOMAIN}', secrets.token_urlsafe(18)
    account = stack.create_account(username, password)
    _, login = stack.login(username, password)
    assert login.status_code == 200, login.text[:300]
    session = bearer(login.json()['access_token'])
    api = bearer(stack.admin_json('POST', f'{account}/generate_api_token')['token'])
    assert stack.signed_in_as(session) == account
    assert stack.signed_in_as(api) == account

    renamed = stack.patch_user(account, username=f'Case.Rename@{USER_DOMAIN}')
    assert renamed.status_code == 200, renamed.text[:300]

    assert stack.signed_in_as(session) == 'login'
    assert stack.signed_in_as(api) == 'login'
    _, login = stack.login(f'Case.Rename@{USER_DOMAIN}', password)
    assert stack.signed_in_as(bearer(login.json()['access_token'])) == account


# Deletes an account and writes it back with the same id and username, as an
# account recreated under a reused id (SQLite reuses ids; a restore can too).
_RECREATE = (
    'CREATE TEMP TABLE recreated AS SELECT * FROM "user" WHERE id = :\'id\';\n'
    'DELETE FROM "user" WHERE id = :\'id\';\n'
    'UPDATE recreated SET created = {created};\n'
    'INSERT INTO "user" SELECT * FROM recreated;\n'
)


def _sessions_then_recreate(stack, local_part: str, created: str):
    username, password = f'{local_part}@{USER_DOMAIN}', secrets.token_urlsafe(18)
    account = stack.create_account(username, password)
    _, login = stack.login(username, password)
    assert login.status_code == 200, login.text[:300]
    sessions = {
        'session': bearer(login.json()['access_token']),
        'pre-WP-0k session': bearer(_pre_wp0k_session(username)),
    }
    for session in sessions.values():
        assert stack.signed_in_as(session) == account

    time.sleep(1.1)  # `iat` and `created` compare to the second.
    stack.sql(_RECREATE.format(created=created), id=account.rsplit('/', 1)[1])
    return account, sessions


def test_an_account_recreated_with_its_id_and_username_ends_its_sessions(stack):
    '''WP-0k INV-3 rows T-1 and T-3. The account is deleted and written back
    with the same id and username, created in a later second than its
    sessions were issued.
    Before WP-0k: its session and its pre-WP-0k session signed in the new row.
    After: both anonymous: the account was created after their `iat`.'''
    account, sessions = _sessions_then_recreate(stack, 'recreated-same-id', 'now()')

    assert {kind: stack.signed_in_as(s) for kind, s in sessions.items()} == {
        kind: 'login' for kind in sessions
    }, account


def test_an_account_recreated_with_no_created_time_keeps_its_sessions(stack):
    '''Residual, accepted (WP-0k INV-3 T-3, "No `created`"; human acceptance
    list). The same recreate, but the row has no `created`, as rows written
    outside the ORM or before migration 853e0e8aa6a0 do: nothing says when it
    was created, so its sessions sign it in, before and after WP-0k.'''
    account, sessions = _sessions_then_recreate(stack, 'recreated-no-created', 'NULL')

    assert {kind: stack.signed_in_as(s) for kind, s in sessions.items()} == {
        kind: account for kind in sessions
    }


def test_an_api_token_revoked_in_the_database_is_refused_on_the_next_request(stack):
    '''WP-0k INV-3 row T-2: nothing caches a token's validity.
    Before WP-0k: the validity was memoised in Redis for 10 minutes, so a
    token revoked outside `update_user_api_tokens` (which cleared the memo)
    kept answering 200.
    After: 401 on the next request.'''
    holder = stack.ensure_user('token-sql-revoked', [])
    issued = stack.admin_json('POST', f'{holder.user_uri}/generate_api_token')
    used = bearer(issued['token'])
    assert stack.request(used, 'GET', PROBE).status_code == 200

    stack.sql(
        'UPDATE api_token SET is_revoked = true WHERE id = :\'id\';', id=issued['id']
    )

    assert stack.request(used, 'GET', PROBE).status_code == 401
