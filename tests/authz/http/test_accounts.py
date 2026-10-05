'''Which account a username, a rename or a deactivation reaches (WP-0k).

WP-0k matches typed usernames for equality ignoring case instead of with ILIKE,
where `_` and `%` are wildcards, and refuses any new username equal ignoring
case to another account's. It also signs in no deactivated account on any path
(decision 0010). Each pin names its WP-0k INV-3 row and states the answer
before WP-0k (integration f5d5993) and after.

Look-alikes are pairs such as `look.alike@` and `look_alike@`: before WP-0k
`look_alike@` pattern-matched both, and `first()` returned the older account.
Accounts that only older code could make (case-only pairs, a pending invitation
equal to a registered account ignoring case) are written in the database
directly (`Stack.rewrite_account`).
'''

from __future__ import annotations

import re
import secrets

import pytest

from tests.authz.http.stack import (
    PENDING,
    TIMEOUT_SECONDS,
    USER_DOMAIN,
    bearer,
    login_session_cookie,
    mint_token,
    new_session,
    password_session,
)

# Any signed-in user may list roles (sitewide view_resource); anonymous gets 401.
PROBE = '/api2/role'
TAKEN_USERNAME = 'Another account has this username.'
_CSRF = re.compile(r'name="csrf_token" type="hidden" value="([^"]+)"')


def _name(local_part: str) -> str:
    return f'{local_part}@{USER_DOMAIN}'


def _password() -> str:
    return secrets.token_urlsafe(18)


def _id(uri: str) -> str:
    return uri.rsplit('/', 1)[1]


def _username(stack, uri: str) -> str:
    return stack.admin_json('GET', uri)['username']


def _login_token_session(stack, username: str, password: str):
    _, response = stack.login(username, password)
    assert response.status_code == 200, (username, response.text[:300])
    return bearer(response.json()['access_token'])


def _change_username_page(stack, username: str, password: str, new_username: str):
    '''Submits flask-user's change-username form as the account, signed in by
    the login headers, with the form's CSRF token.'''
    session = password_session(username, password)
    form = stack.request(session, 'GET', '/user/change-username')
    assert form.status_code == 200, form.status_code
    return session.post(
        f'{stack.base_url}/user/change-username',
        data={
            'csrf_token': _CSRF.search(form.text).group(1),
            'next': '/',
            'new_username': new_username,
            'old_password': password,
        },
        allow_redirects=False,
        timeout=TIMEOUT_SECONDS,
    )


def _set_status(stack, uri: str, status: str) -> None:
    response = stack.patch_user(uri, status=status)
    assert response.status_code == 200, response.text[:300]


def test_a_look_alike_signs_in_its_own_account_by_password(stack):
    '''WP-0k INV-3 row U-1. `look_alike@` beside the older `look.alike@`.
    Before WP-0k: the look-alike's password login got 400 and its login
    headers 401: the typed username found the older account, whose password
    did not match.
    After: both sign in the look-alike. Control: the older account still
    signs in itself.'''
    older_password, look_alike_password = _password(), _password()
    older = stack.create_account(_name('look.alike'), older_password)
    look_alike = stack.create_account(_name('look_alike'), look_alike_password)

    session = _login_token_session(stack, _name('look_alike'), look_alike_password)
    assert stack.signed_in_as(session) == look_alike
    headers = password_session(_name('look_alike'), look_alike_password)
    assert stack.signed_in_as(headers) == look_alike

    session = _login_token_session(stack, _name('look.alike'), older_password)
    assert stack.signed_in_as(session) == older


def test_a_look_alike_api_token_signs_in_its_own_account(stack):
    '''WP-0k INV-3 rows U-1 and T-2. An API token issued to `token_alike@`
    beside the older `token.alike@`.
    Before WP-0k: it signed in the older account (the token's username,
    pattern-matched, `first()`): a look-alike's token reached another account.
    After: it signs in the account it was issued to.'''
    stack.create_account(_name('token.alike'), _password())
    look_alike = stack.create_account(_name('token_alike'), _password())
    issued = stack.admin_json('POST', f'{look_alike}/generate_api_token')

    assert stack.signed_in_as(bearer(issued['token'])) == look_alike


def test_a_look_alike_rename_by_patch_signs_in_only_the_renamed_account(stack):
    '''WP-0k INV-3 row U-5, unit 9 (WP-0j security C1). An admin renames an
    account to `patch_alike@`, which pattern-matches the older `patch.alike@`.
    Before WP-0k: the rename was accepted, then the renamed account's password
    login got 400 (its new username found the older account).
    After: the rename is accepted and the new username signs in only the
    renamed account; the older account still signs in itself.'''
    older_password, password = _password(), _password()
    older = stack.create_account(_name('patch.alike'), older_password)
    renamed = stack.create_account(_name('patch-alike-source'), password)

    response = stack.patch_user(renamed, username=_name('patch_alike'))
    assert response.status_code == 200, response.text[:300]

    session = _login_token_session(stack, _name('patch_alike'), password)
    assert stack.signed_in_as(session) == renamed
    assert stack.signed_in_as(password_session(_name('patch_alike'), password)) == (
        renamed
    )
    session = _login_token_session(stack, _name('patch.alike'), older_password)
    assert stack.signed_in_as(session) == older


def test_a_look_alike_rename_on_the_page_signs_in_only_the_renamed_account(stack):
    '''WP-0k INV-3 row U-5, unit 9. A user renames itself on flask-user's
    change-username page to `page_alike@`, which pattern-matches the older
    `page.alike@`.
    Before WP-0k: the page refused it ("already in use": flask-user's ILIKE
    lookup found the older account).
    After: the page accepts it (302), and the new username signs in only the
    renamed account; the older account still signs in itself.'''
    older_password, password = _password(), _password()
    older = stack.create_account(_name('page.alike'), older_password)
    renamed = stack.create_account(_name('page-alike-source'), password)

    response = _change_username_page(
        stack, _name('page-alike-source'), password, _name('page_alike')
    )
    assert response.status_code == 302, (
        response.status_code,
        'already in use' in response.text,
    )
    assert _username(stack, renamed) == _name('page_alike')

    session = _login_token_session(stack, _name('page_alike'), password)
    assert stack.signed_in_as(session) == renamed
    session = _login_token_session(stack, _name('page.alike'), older_password)
    assert stack.signed_in_as(session) == older


def test_a_case_twin_rename_by_patch_is_refused(stack):
    '''WP-0k INV-3 row U-5. An admin renames an account to `PATCH.TWIN@`,
    equal ignoring case to another account's `patch.twin@`.
    Before WP-0k: 200, and the two accounts became a case-only pair.
    After: 400 `Another account has this username.`, and nothing is written.'''
    stack.create_account(_name('patch.twin'), _password())
    other = stack.create_account(_name('patch-twin-source'), _password())

    response = stack.patch_user(other, username=_name('PATCH.TWIN'))

    assert response.status_code == 400, response.text[:300]
    assert TAKEN_USERNAME in response.text
    assert _username(stack, other) == _name('patch-twin-source')


def test_a_case_twin_rename_on_the_change_username_page_is_refused(stack):
    '''Control, the same before and after WP-0k (row U-5): the page shows the
    form again with "already in use" and renames nothing.'''
    stack.create_account(_name('page.twin'), _password())
    password = _password()
    other = stack.create_account(_name('page-twin-source'), password)

    response = _change_username_page(
        stack, _name('page-twin-source'), password, _name('PAGE.TWIN')
    )

    assert response.status_code == 200
    assert 'already in use' in response.text
    assert _username(stack, other) == _name('page-twin-source')


def test_an_edit_that_keeps_the_username_of_a_case_only_pair_is_accepted(stack):
    '''Control, the same before and after WP-0k (row U-5): only a changed
    username is checked, so an account of a case-only pair made before WP-0k
    can still be edited.'''
    stack.create_account(_name('edit.pair'), _password())
    second = stack.create_account(_name('edit-pair-twin'), _password())
    stack.rewrite_account(second, _name('Edit.Pair'))

    response = stack.patch_user(second, firstName='Edited')

    assert response.status_code == 200, response.text[:300]
    assert stack.admin_json('GET', second)['firstName'] == 'Edited'


def test_creating_a_case_twin_through_the_user_api_is_refused(stack):
    '''WP-0k INV-3 row U-8. `POST /api2/user` with `Create.Twin@` while
    `create.twin@` exists.
    Before WP-0k: 200, a second account equal ignoring case.
    After: 400 `Another account has this username.`; nothing written.'''
    stack.create_account(_name('create.twin'), _password())

    response = stack.request(
        stack.admin,
        'POST',
        '/api2/user',
        {
            'username': _name('Create.Twin'),
            'firstName': 'Authz',
            'lastName': 'Twin',
            'phoneNumber': '',
            'status': 'active',
        },
    )
    if response.status_code < 300:
        stack.created_users.add(response.json()['$uri'])

    assert response.status_code == 400, response.text[:300]
    assert TAKEN_USERNAME in response.text
    rows = stack.sql(
        'SELECT count(*) FROM "user" WHERE lower(username) = lower(:\'username\');',
        username=_name('create.twin'),
    )
    assert rows == [('1',)]


def _register(stack, username: str, invite: str, password: str):
    session = new_session()
    response = stack.request(
        session,
        'POST',
        '/api2/authentication/register',
        {
            'email': username,
            'firstname': 'Authz',
            'lastname': 'Invitee',
            'password': password,
            'invite_token': invite,
        },
    )
    return session, response


def _status_id(stack, uri: str) -> str:
    return stack.sql('SELECT status_id FROM "user" WHERE id = :\'id\';', id=_id(uri))[
        0
    ][0]


def test_registering_a_pending_account_signs_in_that_account(stack):
    '''Control, the same before and after WP-0k: an invitee registers its
    pending account and the registration's cookie signs it in.'''
    shell = stack.create_account(_name('register-alone-source'), _password())
    invite = secrets.token_urlsafe(24)
    stack.rewrite_account(shell, _name('register-alone'), PENDING, invite)

    session, response = _register(stack, _name('register-alone'), invite, _password())

    assert response.status_code == 200, response.text[:300]
    assert _status_id(stack, shell) == '1'
    assert stack.signed_in_as(session) == shell


def test_registering_a_pending_case_twin_of_a_registered_account_is_refused(stack):
    '''WP-0k INV-3 row U-7. A pending invitation `Register.Twin@` (made by the
    case-blind invitations before WP-0k) beside a registered `register.twin@`.
    Before WP-0k: 200, a second active account equal ignoring case, to which
    sessions naming that username could move.
    After: 400 `Another account has this email address`; the invitation stays
    pending.'''
    stack.create_account(_name('register.twin'), _password())
    shell = stack.create_account(_name('register-twin-source'), _password())
    invite = secrets.token_urlsafe(24)
    stack.rewrite_account(shell, _name('Register.Twin'), PENDING, invite)

    _, response = _register(stack, _name('Register.Twin'), invite, _password())

    assert response.status_code == 400, response.text[:300]
    assert 'Another account has this email address' in response.text
    assert _status_id(stack, shell) == str(PENDING)


def test_admin_reset_mails_the_account_it_authorised(stack):
    '''WP-0k INV-3 row U-6. The admin resets the password of a pending
    `reset.twin@` beside an active `Reset.Twin@`.
    The reset link is stored on, and mailed to, the account the route
    authorised, by id. Integration f5d5993 looked it up again by exact
    username, which found the same account, so this holds there too; WP-0k's
    unit 4 to 11 code (e3a7064) looked it up ignoring case and mailed the
    active twin, and unit 12 fixed that.'''
    active = stack.create_account(_name('Reset.Twin'), _password())
    shell = stack.create_account(_name('reset-twin-source'), _password())
    stack.rewrite_account(active, _name('Reset.Twin'))  # no reset link stored
    stack.rewrite_account(shell, _name('reset.twin'), PENDING)
    stack.clear_mail()

    response = stack.request(stack.admin, 'POST', f'{shell}/reset_password')

    assert response.status_code < 300, response.text[:300]
    rows = stack.sql(
        'SELECT id FROM "user" WHERE reset_password_token <> \'\' '
        'AND id IN (:\'active\', :\'shell\');',
        active=_id(active),
        shell=_id(shell),
    )
    assert rows == [(_id(shell),)]
    assert stack.mail_recipients() == [[_name('reset.twin')]]


def test_a_deactivated_account_password_login_is_refused_like_a_wrong_password(
    stack,
):
    '''WP-0k INV-3 row D-1 (decision 0010).
    Before WP-0k: the right password signed a deactivated account in (200,
    a new 365-day token).
    After: 400 with the same body as a wrong password. Control: reactivated,
    the password signs in again.'''
    password = _password()
    account = stack.create_account(_name('deactivated-login'), password)
    _, wrong = stack.login(_name('deactivated-login'), 'not-the-password')
    assert wrong.status_code == 400, wrong.text[:300]

    _set_status(stack, account, 'inactive')
    _, right = stack.login(_name('deactivated-login'), password)
    assert (right.status_code, right.json()) == (400, wrong.json())

    _set_status(stack, account, 'active')
    session = _login_token_session(stack, _name('deactivated-login'), password)
    assert stack.signed_in_as(session) == account


def test_a_deactivated_account_header_login_is_refused(stack):
    '''WP-0k INV-3 row D-2.
    Before WP-0k: `X-Username` and `X-Password` signed a deactivated account
    in (200).
    After: anonymous, 401 on API routes and the sign-in page on pages.
    Control: reactivated, the headers sign in again.'''
    password = _password()
    account = stack.create_account(_name('deactivated-headers'), password)
    session = password_session(_name('deactivated-headers'), password)
    assert stack.request(session, 'GET', PROBE).status_code == 200

    _set_status(stack, account, 'inactive')
    assert stack.request(session, 'GET', PROBE).status_code == 401
    assert stack.signed_in_as(session) == 'login'

    _set_status(stack, account, 'active')
    assert stack.signed_in_as(session) == account


def _signed_in_session(stack, kind: str, username: str, password: str, uri: str):
    account_id = int(_id(uri))
    render_claims = {'needs': [['view_resource', 1, 'dashboard']], 'query_needs': ['*']}
    if kind == 'login token':
        return _login_token_session(stack, username, password)
    if kind == 'login cookie':
        session, response = stack.login(username, password, set_cookie=True)
        assert response.status_code == 200, response.text[:300]
        return session
    if kind == 'pre-WP-0k session':
        return bearer(
            mint_token(
                username, {'needs': ['*'], 'query_needs': ['*'], 'remember_me': False}
            )
        )
    if kind == 'api token':
        return bearer(stack.admin_json('POST', f'{uri}/generate_api_token')['token'])
    if kind == 'render token':
        # As `grid_dashboard_urlbox_renderer` mints it since WP-0k.
        return bearer(mint_token(username, {**render_claims, 'user_id': account_id}))
    if kind == 'pre-WP-0k render token':
        return bearer(mint_token(username, render_claims))
    assert kind == 'flask-login session', kind
    return login_session_cookie(account_id)


@pytest.mark.parametrize(
    'kind',
    [
        'login token',
        'login cookie',
        'pre-WP-0k session',
        'api token',
        'render token',
        'pre-WP-0k render token',
        'flask-login session',
    ],
)
def test_a_token_issued_before_deactivation_signs_in_nobody(stack, kind):
    '''WP-0k INV-3 rows D-3 and D-4.
    Before WP-0k: every token, cookie and session issued before the account
    was deactivated kept signing it in.
    After: anonymous from the next request. Control: reactivated, the same
    token signs the account in again, so the refusal is the status alone.'''
    username, password = _name(f'deactivated-{kind.replace(" ", "-")}'), _password()
    account = stack.create_account(username, password)
    session = _signed_in_session(stack, kind, username, password, account)
    assert stack.signed_in_as(session) == account

    _set_status(stack, account, 'inactive')
    assert stack.signed_in_as(session) == 'login'

    _set_status(stack, account, 'active')
    assert stack.signed_in_as(session) == account
