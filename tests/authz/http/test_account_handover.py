'''Username changes and password resets of users who hold more than the caller
(H5, WP-0j, decisions 0005 and 0010).

Renaming a user to an address the caller reads and then resetting the password
hands the caller the account. Since WP-0j a non-superuser may rename, or reset
the password of, only a user whose roles, groups and ACLs are among its own
(403 otherwise). Decision 0010 also hides administrators through a group from
non-superusers, as direct administrators are: 404 on every user item route and
left out of the user list. A non-superuser's group member list keeps the
administrators it cannot see, and naming one is a 404 (INV-3 row 7).

Each refusal below pins the behaviour after WP-0j. Before WP-0j (WP-0h head
488e482) the same request succeeds: the rename answers 200 and writes the new
username, and the reset answers 204, stores a reset token and mails the link to
the username; every user route reaches an administrator through a group, and
the user list shows them, and a dashboard names its administrator author. The
controls are unchanged and pass on both trees. The rename over 50 characters is
pinned as it is; owner WP-5d.

What HTTP cannot show is read from the stack's containers (`AUTHZ_PROJECT`, as
for tests/authz/stack.sh): the target's rows in Postgres, the reset token, the
mailpit sink and the web log's audit lines. Outside production the mail goes out
inside the request (`NotificationService._run_task` uses `apply`), so a count
read after the response is final; the controls' one-mail assertions show the
sink is read correctly. Mail is counted per address before and after the
request, because creating a dashboard also mails its author.
'''

from __future__ import annotations

import json
import os
import secrets
import subprocess

import pytest

_PROJECT = os.environ.get('AUTHZ_PROJECT', 'harmony-wp2b-authz')
_EDITOR = ('manager', 'user_admin')
_RENAME_REFUSED = (
    'You may only change the username of users whose access you hold yourself.'
)
_RESET_REFUSED = (
    'You may only reset the password of users whose access you hold yourself.'
)
_DASHBOARD_SPECIFICATION = {
    'version': '2023-06-30',
    'items': [],
    'options': {'title': 'Authz handover dashboard', 'columnCount': 100},
    'commonSettings': {
        'filterSettings': {
            'enabledCategories': [],
            'excludedTiles': [],
            'items': [],
            'visible': False,
            'enabledFilterHierarchy': [],
        },
        'groupingSettings': {
            'enabledCategories': [],
            'excludedTiles': [],
            'items': [],
            'visible': False,
        },
        'panelAlignment': 'LEFT',
    },
    'legacy': False,
}
_MAILPIT_COUNT = (
    'import sys, requests; '
    'r = requests.get("http://mailpit:8025/api/v1/search", '
    'params={"query": "to:\\"" + sys.argv[1] + "\\""}, timeout=30); '
    'r.raise_for_status(); print(r.json()["messages_count"])'
)


def _docker(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ['docker', *args], input=stdin, check=True, capture_output=True, text=True
    ).stdout


def _sql(query: str, user_id: int) -> str:
    '''Runs `query` with `:user_id` bound by psql (read from stdin, where psql
    interpolates variables).'''
    return _docker(
        'exec',
        '-i',
        f'{_PROJECT}-postgres-1',
        'psql',
        '-U',
        'postgres',
        '-d',
        'harmony_demo-local',
        '-tA',
        '-v',
        f'user_id={int(user_id)}',
        '-f',
        '-',
        stdin=query,
    ).strip()


def _mails_to(address: str) -> int:
    return int(
        _docker('exec', f'{_PROJECT}-web-1', 'python', '-c', _MAILPIT_COUNT, address)
    )


def _audit_lines() -> list:
    logs = subprocess.run(
        ['docker', 'logs', f'{_PROJECT}-web-1'],
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        line for line in (logs.stdout + logs.stderr).splitlines() if 'Refused' in line
    ]


def _id(session) -> int:
    return int(session.user_uri.rsplit('/', 1)[1])


def _username(session) -> str:
    return session.headers['X-Username']


_STATE_QUERIES = {
    'user': 'select row_to_json(u)::text from "user" u where id = :user_id',
    'roles': "select coalesce(string_agg(role_id::text, ',' order by role_id), '') "
    'from user_roles where user_id = :user_id',
    'groups': "select coalesce(string_agg(group_id::text, ',' order by group_id), '') "
    'from security_group_users where user_id = :user_id',
    'acls': "select coalesce(string_agg(resource_role_id || ':' || resource_id, ',' "
    "order by id), '') from user_acl where user_id = :user_id",
}


def _state(user_id: int) -> dict:
    '''Everything a rename or a reset could write for the user.'''
    return {name: _sql(query, user_id) for name, query in _STATE_QUERIES.items()}


def _stored(user_id: int) -> tuple:
    '''(username, last name, reset token) as stored.'''
    username, last_name, token = _sql(
        'select username, last_name, reset_password_token from "user" '
        'where id = :user_id',
        user_id,
    ).split('|')
    return username, last_name, token


def _attacker_address() -> str:
    return f'attacker-{secrets.token_hex(4)}@escalation.test'


class _World:
    '''Users, groups and dashboards for one test, each fresh. Users go with the
    stack's cleanup; groups and dashboards are deleted here, dashboards first so
    their authors can be deleted.'''

    def __init__(self, stack, tag):
        self.stack = stack
        self.tag = tag
        self._count = 0
        self._groups: list = []
        self._dashboards: list = []
        self._roles: list = []
        self.group_uris: dict = {}

    def user(self, roles=()):
        self._count += 1
        session = self.stack.ensure_user(f'handover-{self.tag}-{self._count}', roles)
        self.group_uris[session.user_uri] = []
        return session

    def exporting_role(self) -> str:
        '''A fresh role that allows data export and nothing else; its URI.'''
        label = f'authz handover export {self.tag} {len(self._roles)}'
        role = self.stack.admin_json(
            'POST',
            '/api2/role',
            {
                '$uri': '',
                'name': '',
                'label': label,
                'alertResourceRoleName': '',
                'dashboardResourceRoleName': '',
                'permissions': [],
                'queryPolicies': [],
                'dataExport': True,
            },
        )
        self._roles.append(role['$uri'])
        return role['$uri']

    def group(self, roles, members) -> str:
        '''A group carrying `roles` (names, or URIs as `exporting_role` gives).'''
        name = f'authz-handover-{self.tag}-{len(self._groups)}'
        role_uris = self.stack.roles_by_name()
        self.stack.admin_json(
            'POST',
            '/api2/group',
            {
                '$uri': '',
                'name': name,
                'roles': [role_uris.get(role, role) for role in roles],
                'users': [_username(member) for member in members],
                'acls': [],
            },
        )
        uri = next(
            group['$uri']
            for group in self.stack.admin_json('GET', '/api2/group?per_page=500')
            if group['name'] == name
        )
        self._groups.append(uri)
        for member in members:
            self.group_uris[member.user_uri].append(uri)
        return uri

    def dashboard_by(self, author) -> str:
        '''The author creates a dashboard, which gives it a dashboard_admin ACL
        on it. Returns the dashboard's URI.'''
        response = self.stack.request(
            author,
            'POST',
            '/api2/dashboard',
            {
                'slug': f'authz-handover-{self.tag}-{len(self._dashboards)}',
                'specification': _DASHBOARD_SPECIFICATION,
            },
        )
        assert response.status_code < 300, (response.status_code, response.text[:300])
        self._dashboards.append(response.json()['$uri'])
        acls = self.stack.admin_json('GET', author.user_uri)['acls']
        assert [acl['resourceRole']['name'] for acl in acls] == ['dashboard_admin']
        return self._dashboards[-1]

    def body(self, target, username=None, last_name=None, **overrides) -> dict:
        '''A `PATCH /api2/user/<id>` body as the admin UI sends it: every role,
        group and ACL of the user sent again, then `overrides`.'''
        current = self.stack.admin_json('GET', target.user_uri)
        return {
            '$uri': target.user_uri,
            'username': current['username'] if username is None else username,
            'firstName': current['firstName'],
            'lastName': current['lastName'] if last_name is None else last_name,
            'phoneNumber': '',
            'status': 'active',
            'acls': current['acls'],
            'apiTokens': [],
            'roles': [role['$uri'] for role in current['roles']],
            'groups': self.group_uris[target.user_uri],
            **overrides,
        }

    def rename(self, caller, target, username=None, last_name='Renamed'):
        return self.stack.request(
            caller,
            'PATCH',
            target.user_uri,
            self.body(target, username or _attacker_address(), last_name),
        )

    def reset(self, caller, target):
        return self.stack.request(caller, 'POST', f'{target.user_uri}/reset_password')

    def cleanup(self) -> None:
        for uri in self._dashboards + self._groups + self._roles:
            response = self.stack.request(self.stack.admin, 'DELETE', uri)
            assert response.status_code in (200, 204, 404), (uri, response.status_code)


@pytest.fixture(name='world')
def fixture_world(stack):
    world = _World(stack, secrets.token_hex(3))
    try:
        yield world
    finally:
        world.cleanup()


# Targets holding something the caller does not. Each returns
# (caller roles, target).


def _admin_through_group(world):
    target = world.user()
    world.group(['admin'], [target])
    return _EDITOR, target


def _default_role_holder(world):
    '''_default_role carries the seeded all-values query policies.'''
    return _EDITOR, world.user(['_default_role'])


def _foreign_group_member(world):
    '''The group grants nothing the caller lacks; membership is the grant.'''
    target = world.user()
    world.group(['manager'], [target])
    return _EDITOR, target


def _exporter_group_member(world):
    '''The group carries a role the caller lacks, one that allows data export.'''
    target = world.user()
    world.group([world.exporting_role()], [target])
    return _EDITOR, target


def _dashboard_author(world):
    '''Caller and author both hold _default_role; only the author's
    dashboard_admin ACL on its dashboard differs.'''
    target = world.user(['_default_role'])
    world.dashboard_by(target)
    return (*_EDITOR, '_default_role'), target


# Non-administrators who hold more than the caller: the WP-0j guard refuses.
_HOLDING_MORE = pytest.mark.parametrize(
    'make_target',
    [
        _default_role_holder,
        _foreign_group_member,
        _exporter_group_member,
        _dashboard_author,
    ],
    ids=lambda make_target: make_target.__name__.lstrip('_'),
)


def _assert_refused(response, message, caller, before_audit, target, before_state):
    assert response.status_code == 403, response.text[:300]
    assert response.json()['message'] == message
    assert _state(_id(target)) == before_state
    new_lines = _audit_lines()[len(before_audit) :]
    assert len(new_lines) == 1, new_lines
    assert f'(Id:{_username(caller)}' in new_lines[0]
    assert f'User {_id(target)} holds' in new_lines[0]


@_HOLDING_MORE
def test_user_editor_cannot_rename_a_user_holding_more(world, make_target):
    '''Before WP-0j: 200 and the username, last name and resent grants written.
    After: 403, nothing written, one audit line.'''
    caller_roles, target = make_target(world)
    caller = world.user(caller_roles)
    before_state, before_audit = _state(_id(target)), _audit_lines()

    response = world.rename(caller, target)

    _assert_refused(
        response, _RENAME_REFUSED, caller, before_audit, target, before_state
    )
    assert 'admin' not in response.text and '/api2/' not in response.text


@_HOLDING_MORE
def test_user_editor_cannot_reset_a_user_holding_more(world, make_target):
    '''Before WP-0j: 204, a reset token stored and one mail to the target.
    After: 403, no token, no mail, one audit line.'''
    caller_roles, target = make_target(world)
    caller = world.user(caller_roles)
    before_state, before_audit = _state(_id(target)), _audit_lines()
    before_mails = _mails_to(_username(target))

    response = world.reset(caller, target)

    _assert_refused(
        response, _RESET_REFUSED, caller, before_audit, target, before_state
    )
    assert _stored(_id(target))[2] == ''
    assert _mails_to(_username(target)) == before_mails


@pytest.mark.parametrize('caller_role', ['user_admin', 'user_moderator'])
def test_a_reset_caller_cannot_reset_a_user_holding_more(world, caller_role):
    '''The other holders of reset_password on user, on a _default_role holder.
    Before WP-0j: 204, a token and one mail. After: 403, no token, no mail,
    one audit line.'''
    _, target = _default_role_holder(world)
    caller = world.user([caller_role])
    before_state, before_audit = _state(_id(target)), _audit_lines()
    before_mails = _mails_to(_username(target))

    response = world.reset(caller, target)

    _assert_refused(
        response, _RESET_REFUSED, caller, before_audit, target, before_state
    )
    assert _stored(_id(target))[2] == ''
    assert _mails_to(_username(target)) == before_mails


_ITEM_REQUESTS = {
    'rename': lambda world, caller, target: world.rename(caller, target),
    'profile edit': lambda world, caller, target: world.rename(
        caller, target, _username(target), last_name='Edited'
    ),
    'reset': lambda world, caller, target: world.reset(caller, target),
    'read': lambda world, caller, target: world.stack.request(
        caller, 'GET', target.user_uri
    ),
    'delete': lambda world, caller, target: world.stack.request(
        caller, 'DELETE', target.user_uri
    ),
    'force delete': lambda world, caller, target: world.stack.request(
        caller, 'DELETE', f'{target.user_uri}/force'
    ),
    'deactivate': lambda world, caller, target: world.stack.request(
        caller, 'PATCH', target.user_uri, world.body(target, status='inactive')
    ),
    'demote': lambda world, caller, target: world.stack.request(
        caller, 'PATCH', target.user_uri, world.body(target, groups=[])
    ),
    'clear roles': lambda world, caller, target: world.stack.request(
        caller, 'PATCH', f'{target.user_uri}/roles', {}
    ),
}


@pytest.mark.parametrize(
    'caller_roles,action',
    [
        (_EDITOR, 'rename'),
        (_EDITOR, 'profile edit'),
        (_EDITOR, 'reset'),
        (('user_admin',), 'reset'),
        (('user_moderator',), 'reset'),
        (_EDITOR, 'read'),
        (('user_admin',), 'delete'),
        (('manager',), 'force delete'),
        (_EDITOR, 'deactivate'),
        (_EDITOR, 'demote'),
        (('user_admin',), 'clear roles'),
    ],
    ids=lambda value: value if isinstance(value, str) else ' + '.join(value),
)
def test_an_admin_through_a_group_is_not_found_by_a_non_superuser(
    world, caller_roles, action
):
    '''Decision 0010. Before WP-0j: rename, profile edit, read, deactivate,
    demote and clear roles 200, reset 204 with a token and a mail, delete and
    force delete 204 (the account gone). With WP-0j's guard alone (b090396):
    rename and reset 403 with an audit line, the rest as before. After: 404 on
    every route, nothing written, no mail, no audit line, as for a direct
    administrator.'''
    _, target = _admin_through_group(world)
    caller = world.user(caller_roles)
    before_state, before_audit = _state(_id(target)), _audit_lines()
    before_mails = _mails_to(_username(target))

    response = _ITEM_REQUESTS[action](world, caller, target)

    assert response.status_code == 404, response.text[:300]
    assert _state(_id(target)) == before_state
    assert _mails_to(_username(target)) == before_mails
    assert _audit_lines() == before_audit


def _listed_uris(stack, session) -> set:
    '''The user URIs the pickers (dashboard sharing and user management, e-mail
    recipients, alert recipients, group editors) get: `DirectoryService.getUsers`
    fetches `GET /api2/user?per_page=1000` once.'''
    response = stack.request(session, 'GET', '/api2/user?per_page=1000')
    assert response.status_code == 200, response.text[:300]
    return {user['$uri'] for user in response.json()}


def _looked_up(stack, session, username) -> list:
    '''`DirectoryService.getUser`: `GET /api2/user?where={"username": ...}`.'''
    where = json.dumps({'username': username})
    response = stack.request(session, 'GET', f'/api2/user?where={where}')
    assert response.status_code == 200, response.text[:300]
    return [user['$uri'] for user in response.json()]


@pytest.mark.parametrize(
    'caller_roles', [_EDITOR, ('_default_role',), ('dashboard_viewer',)], ids=' + '.join
)
def test_user_pickers_do_not_offer_an_admin_through_a_group(world, caller_roles):
    '''Decision 0010; flips WP-2b's H5 list visibility (part of I1). Before:
    the list and the lookup by username show an administrator through a group
    to every non-superuser. After: neither does, as for direct administrators;
    a user holding more than the caller without being an administrator is
    still offered.'''
    _, hidden = _admin_through_group(world)
    _, shown = _foreign_group_member(world)
    caller = world.user(caller_roles)

    listed = _listed_uris(world.stack, caller)

    assert shown.user_uri in listed
    assert hidden.user_uri not in listed
    assert _looked_up(world.stack, caller, _username(hidden)) == []
    assert _looked_up(world.stack, caller, _username(shown)) == [shown.user_uri]


def test_superuser_lists_an_admin_through_a_group(world):
    _, target = _admin_through_group(world)

    assert target.user_uri in _listed_uris(world.stack, world.stack.admin)
    assert _looked_up(world.stack, world.stack.admin, _username(target)) == [
        target.user_uri
    ]


def _direct_admin(world):
    return _EDITOR, world.user(['admin'])


def _author_username_seen_by(world, session, dashboard_uri) -> tuple:
    '''`authorUsername` of the dashboard on its item route and in the list.'''
    item = world.stack.request(session, 'GET', dashboard_uri)
    assert item.status_code == 200, item.text[:300]
    listing = world.stack.request(session, 'GET', '/api2/dashboard?per_page=1000')
    assert listing.status_code == 200, listing.text[:300]
    listed = [d for d in listing.json() if d['$uri'] == dashboard_uri]
    assert len(listed) == 1, len(listed)
    return item.json()['authorUsername'], listed[0]['authorUsername']


@pytest.mark.parametrize(
    'make_author',
    [_admin_through_group, _direct_admin],
    ids=lambda make_author: make_author.__name__.lstrip('_'),
)
def test_a_dashboard_hides_its_admin_author_from_a_non_superuser(world, make_author):
    '''Decision 0010, WP-0j INV-3 row 6. Before (488e482, and 429bf96): a
    non-superuser who can view the dashboard gets the administrator author's
    username in `authorUsername` on the item route and in the list. After:
    null in both, as the field's description says for an author the caller
    cannot see. The `author` URI is unchanged and answers 404 to that caller;
    a superuser still gets the username.'''
    _, author = make_author(world)
    dashboard_uri = world.dashboard_by(author)
    viewer = world.user(['dashboard_viewer'])

    seen = _author_username_seen_by(world, viewer, dashboard_uri)

    assert seen == (None, None)
    item = world.stack.request(viewer, 'GET', dashboard_uri).json()
    assert item['author'] == author.user_uri
    assert world.stack.request(viewer, 'GET', author.user_uri).status_code == 404
    assert _author_username_seen_by(world, world.stack.admin, dashboard_uri) == (
        _username(author),
        _username(author),
    )


def test_a_dashboard_names_an_author_who_is_not_an_admin(world):
    '''Unchanged: an author the viewer can see is named on both routes.'''
    author = world.user(['_default_role'])
    dashboard_uri = world.dashboard_by(author)
    viewer = world.user(['dashboard_viewer'])

    assert _author_username_seen_by(world, viewer, dashboard_uri) == (
        _username(author),
        _username(author),
    )


def test_user_editor_cannot_take_over_an_admin_through_a_group(world):
    '''H5 end to end: rename to an address the caller reads, then reset.
    Before WP-0j: 200 then 204, and the reset link reaches the attacker's
    address (one mail). After: both refused, the username kept, no token, no
    mail to the attacker. Both answer 404: decision 0010 hides the target.'''
    _, target = _admin_through_group(world)
    caller = world.user(_EDITOR)
    original = _username(target)
    attacker = _attacker_address()
    before_mails = _mails_to(original)

    renamed = world.rename(caller, target, attacker)
    reset = world.reset(caller, target)

    # The takeover itself first: the reset link must not reach the attacker.
    assert _mails_to(attacker) == 0
    assert (renamed.status_code, reset.status_code) == (404, 404)
    assert _stored(_id(target))[0] == original
    assert _stored(_id(target))[2] == ''
    assert _mails_to(original) == before_mails


# Unchanged by WP-0j and decision 0010: targets holding nothing the caller does
# not, superusers, and callers the route gates already stop.


def _equal_roles(world):
    return _EDITOR, world.user(_EDITOR)


def _no_grants(world):
    return _EDITOR, world.user()


def _shared_group_member(world):
    caller, target = world.user(_EDITOR), world.user()
    world.group(['manager'], [caller, target])
    return caller, target


def _default_role_holder_with_caller_holding_it(world):
    return (*_EDITOR, '_default_role'), world.user(['_default_role'])


def _dashboard_author_with_caller_holding_dashboard_admin(world):
    '''The dashboard_admin role covers the author's ACL sitewide.'''
    _, target = _dashboard_author(world)
    return (*_EDITOR, '_default_role', 'dashboard_admin'), target


_HOLDING_NO_MORE = pytest.mark.parametrize(
    'make_pair',
    [
        _equal_roles,
        _no_grants,
        _shared_group_member,
        _default_role_holder_with_caller_holding_it,
        _dashboard_author_with_caller_holding_dashboard_admin,
    ],
    ids=lambda make_pair: make_pair.__name__.lstrip('_'),
)


def _caller_and_target(world, make_pair):
    caller, target = make_pair(world)
    if isinstance(caller, tuple):
        caller = world.user(caller)
    return caller, target


@_HOLDING_NO_MORE
def test_user_editor_renames_a_user_holding_no_more(world, make_pair):
    caller, target = _caller_and_target(world, make_pair)
    new = _attacker_address()
    before_audit = _audit_lines()

    response = world.rename(caller, target, new, last_name='Renamed')

    assert response.status_code == 200, response.text[:300]
    assert _stored(_id(target))[:2] == (new, 'Renamed')
    assert _audit_lines() == before_audit


@_HOLDING_NO_MORE
def test_user_editor_resets_a_user_holding_no_more(world, make_pair):
    caller, target = _caller_and_target(world, make_pair)
    before_audit, before_mails = _audit_lines(), _mails_to(_username(target))

    response = world.reset(caller, target)

    assert response.status_code == 204, response.text[:300]
    assert _stored(_id(target))[2] != ''
    assert _mails_to(_username(target)) == before_mails + 1
    assert _audit_lines() == before_audit


def test_user_editor_edits_the_profile_of_a_user_holding_more(world):
    '''A PATCH that keeps the username is not a rename.'''
    _, target = _foreign_group_member(world)
    caller = world.user(_EDITOR)
    before_audit = _audit_lines()

    response = world.rename(caller, target, _username(target), last_name='Edited')

    assert response.status_code == 200, response.text[:300]
    assert _stored(_id(target))[:2] == (_username(target), 'Edited')
    assert _audit_lines() == before_audit


def test_superuser_renames_and_resets_an_admin_through_a_group(world):
    _, target = _admin_through_group(world)
    new = _attacker_address()

    renamed = world.rename(world.stack.admin, target, new)
    reset = world.reset(world.stack.admin, target)

    assert (renamed.status_code, reset.status_code) == (200, 204)
    assert _stored(_id(target))[0] == new
    assert _stored(_id(target))[2] != ''
    assert _mails_to(new) == 1


def test_user_editor_resets_its_own_password(world):
    caller = world.user(_EDITOR)
    before_mails = _mails_to(_username(caller))

    response = world.reset(caller, caller)

    assert response.status_code == 204, response.text[:300]
    assert _mails_to(_username(caller)) == before_mails + 1


def test_manager_alone_cannot_reset_a_password(world):
    '''`manager` holds reset_password on site only; the gate needs it on user.'''
    _, target = _no_grants(world)
    caller = world.user(['manager'])
    before_state, before_audit = _state(_id(target)), _audit_lines()
    before_mails = _mails_to(_username(target))

    response = world.reset(caller, target)

    assert response.status_code == 401, response.text[:300]
    assert _state(_id(target)) == before_state
    assert _mails_to(_username(target)) == before_mails
    assert _audit_lines() == before_audit


def test_user_admin_alone_cannot_rename(world):
    '''`user_admin` lacks edit_user on site, the PATCH gate.'''
    _, target = _no_grants(world)
    caller = world.user(['user_admin'])
    before_state, before_audit = _state(_id(target)), _audit_lines()

    response = world.rename(caller, target)

    assert response.status_code == 401, response.text[:300]
    assert _state(_id(target)) == before_state
    assert _audit_lines() == before_audit


@pytest.mark.parametrize('action', ['rename', 'reset'])
def test_a_direct_admin_is_not_found_by_a_user_editor(world, action):
    '''UserResourceManager hides users holding the admin role directly.'''
    target = world.user(['admin'])
    caller = world.user(_EDITOR)
    before_state = _state(_id(target))

    response = getattr(world, action)(caller, target)

    assert response.status_code == 404, response.text[:300]
    assert _state(_id(target)) == before_state


@pytest.mark.parametrize(
    'by_superuser', [False, True], ids=['user_editor', 'superuser']
)
def test_rename_to_more_than_50_characters_is_a_server_error(world, by_superuser):
    '''Pinned as today, before and after WP-0j; owner WP-5d. USERNAME_SCHEMA
    sets no maximum length, so a username longer than the 50-character column
    reaches the database and fails there (500). Nothing is written.'''
    target = world.user()
    caller = world.stack.admin if by_superuser else world.user(_EDITOR)
    long_username = f'{"a" * 52}{secrets.token_hex(2)}@escalation.test'
    before_state = _state(_id(target))

    response = world.rename(caller, target, long_username)

    assert response.status_code == 500
    assert _state(_id(target)) == before_state
    assert response.json()['success'] is False


# Group membership (INV-3 row 7, decision 0010, qa round 2 Medium 1). The group
# editor lists only the users the caller can see, so a member list it saves
# never names a hidden administrator. Before (dd186b0b), saving that list
# removed the administrator, and a list or username naming one added or removed
# them. After, a non-superuser's member list replaces only the members it can
# see, and naming a hidden user is a 404 as for a missing user.


def _members(group_uri: str) -> set:
    group_id = int(group_uri.rsplit('/', 1)[1])
    rows = _docker(
        'exec',
        '-i',
        f'{_PROJECT}-postgres-1',
        'psql',
        '-U',
        'postgres',
        '-d',
        'harmony_demo-local',
        '-tA',
        '-v',
        f'group_id={group_id}',
        '-f',
        '-',
        stdin='select user_id from security_group_users where group_id = :group_id',
    )
    return {int(row) for row in rows.split()}


def _hidden_admin(world, kind: str):
    if kind == 'direct_admin':
        return world.user(['admin'])
    return _admin_through_group(world)[1]


def _group_with_a_hidden_admin(world, kind: str) -> tuple:
    '''A group_admin, a visible member and a hidden administrator share a group
    that carries no role, so the group_admin reaches it.'''
    editor = world.user(['group_admin'])
    member = world.user()
    hidden = _hidden_admin(world, kind)
    group_uri = world.group([], [editor, member, hidden])
    return editor, member, hidden, group_uri


def _set_members_by_patch(world, caller, group_uri, usernames):
    '''What the group editor's Save sends.'''
    name = world.stack.admin_json('GET', group_uri)['name']
    return world.stack.request(
        caller,
        'PATCH',
        group_uri,
        {'$uri': '', 'name': name, 'roles': [], 'users': usernames, 'acls': []},
    )


def _set_members_by_users_route(world, caller, group_uri, usernames):
    return world.stack.request(caller, 'PATCH', f'{group_uri}/users', usernames)


_ADMIN_KINDS = pytest.mark.parametrize('kind', ['direct_admin', 'admin_through_group'])
_SET_MEMBERS = pytest.mark.parametrize(
    'set_members',
    [_set_members_by_patch, _set_members_by_users_route],
    ids=['patch_group', 'patch_group_users'],
)


def _ids(*sessions) -> set:
    return {_id(session) for session in sessions}


@_SET_MEMBERS
@_ADMIN_KINDS
def test_a_group_editor_keeps_an_admin_member_it_cannot_see(world, kind, set_members):
    '''Before: 200 and the administrator removed with the visible member.
    After: 200, the visible member removed, the administrator kept.'''
    editor, member, hidden, group_uri = _group_with_a_hidden_admin(world, kind)

    response = set_members(world, editor, group_uri, [_username(editor)])

    assert response.status_code == 200, response.text[:300]
    assert _members(group_uri) == _ids(editor, hidden)


@_SET_MEMBERS
@_ADMIN_KINDS
def test_a_group_editor_cannot_add_an_admin_it_cannot_see(world, kind, set_members):
    '''Before: 200 and the administrator added. After: 404, nothing changed.'''
    editor, member, hidden, group_uri = _group_with_a_hidden_admin(world, kind)
    outsider = _hidden_admin(world, kind)
    usernames = [_username(editor), _username(member), _username(outsider)]

    response = set_members(world, editor, group_uri, usernames)

    assert response.status_code == 404, response.text[:300]
    assert _members(group_uri) == _ids(editor, member, hidden)


@pytest.mark.parametrize('method', ['POST', 'DELETE'])
@_ADMIN_KINDS
def test_a_group_editor_cannot_add_or_remove_an_admin_by_username(world, kind, method):
    '''Before: 200 or 201, the administrator added (POST) or removed (DELETE).
    After: 404, nothing changed.'''
    editor, member, hidden, group_uri = _group_with_a_hidden_admin(world, kind)
    target = hidden if method == 'DELETE' else _hidden_admin(world, kind)

    response = world.stack.request(
        editor, method, f'{group_uri}/users', _username(target)
    )

    assert response.status_code == 404, response.text[:300]
    assert _members(group_uri) == _ids(editor, member, hidden)


@pytest.mark.parametrize('method', ['POST', 'DELETE'])
def test_a_group_editor_adds_and_removes_users_it_sees_by_username(world, method):
    '''Unchanged: visible users are added and removed by username.'''
    editor, member, hidden, group_uri = _group_with_a_hidden_admin(
        world, 'admin_through_group'
    )
    newcomer = world.user()
    target = member if method == 'DELETE' else newcomer

    response = world.stack.request(
        editor, method, f'{group_uri}/users', _username(target)
    )

    assert response.status_code in (200, 201), response.text[:300]
    expected = (
        _ids(editor, hidden)
        if method == 'DELETE'
        else _ids(editor, member, hidden, newcomer)
    )
    assert _members(group_uri) == expected


@_SET_MEMBERS
@_ADMIN_KINDS
def test_a_superuser_still_sets_any_member_list(world, kind, set_members):
    '''Unchanged: a superuser (here through a group) replaces every member,
    administrators included.'''
    superuser = _hidden_admin(world, 'admin_through_group')
    _, member, hidden, group_uri = _group_with_a_hidden_admin(world, kind)
    outsider = _hidden_admin(world, kind)

    response = set_members(
        world, superuser, group_uri, [_username(member), _username(outsider)]
    )

    assert response.status_code == 200, response.text[:300]
    assert _members(group_uri) == _ids(member, outsider)
