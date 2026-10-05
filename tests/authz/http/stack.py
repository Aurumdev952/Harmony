'''Talks to a live Harmony stack for the HTTP layer of the authorisation suite.

Every seeded role gets one user, `role-<role>@authz.invalid`, created (or
reset) through the admin API with a password generated for this run and never
written anywhere. Requests authenticate with X-Username / X-Password headers,
which load the account's needs without JWT narrowing, like the `role:<name>`
principals of the pure layer. Every user and group the run creates is deleted
when the session ends (`Stack.cleanup`).

Only a loopback stack is accepted: the suite creates and deletes users.

Some account pins need what no API offers: accounts that predate a check (a
case-only pair, a pending twin), tokens minted the way older code minted them,
and the mail a route sent. For those the stack's own containers are used
(`Stack.sql`, `Stack.mail_recipients`), named by `AUTHZ_PROJECT`, and tokens
are signed with the stack's generated keys from `AUTHZ_CREDENTIALS_FILE`.
'''

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TIMEOUT_SECONDS = 120
USER_DOMAIN = 'authz.invalid'
LOOPBACK_HOSTS = ('127.0.0.1', 'localhost', '::1')
DEFAULT_PROJECT = 'harmony-wp2b-authz'
DATABASE = 'harmony_demo-local'
# models.alchemy.user.UserStatusEnum
ACTIVE, PENDING = 1, 3
_BUNDLE = re.compile(r'/([A-Za-z]+)\.bundle\.js')
_BACKEND_JSON = re.compile(r'window\.__JSON_FROM_BACKEND = (.*?);\s*\n')
# Every signed-in user gets this page, and it carries the signed-in user's id.
WHOAMI_PAGE = '/overview'
_FIELD_SEPARATOR = '\x1f'
# The smallest specification `POST /api2/dashboard` accepts (WP-2c's case).
EMPTY_DASHBOARD = {
    'version': '2023-06-30',
    'items': [],
    'options': {'title': 'Authz dashboard', 'columnCount': 100},
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


def outcome(response: requests.Response) -> str:
    '''Classifies a response the way the expectation tables name outcomes:
    `login`, `redirect:<path>`, `page:<last bundle>` for HTML pages, or the
    status code.'''
    if response.status_code in (301, 302, 303, 307):
        path = urlparse(response.headers['Location']).path
        return 'login' if path.endswith('/login') else f'redirect:{path}'
    if response.status_code == 200 and 'text/html' in response.headers.get(
        'Content-Type', ''
    ):
        bundles = _BUNDLE.findall(response.text)
        if bundles:
            return f'page:{bundles[-1]}'
    return str(response.status_code)


def new_session() -> requests.Session:
    '''A session that opens a connection per request. A pooled keep-alive
    connection can be closed by gunicorn just as the next request goes out;
    idempotent requests were retried, but a POST failed with
    RemoteDisconnected (seen once creating a user), so nothing is pooled. The
    retry stays for refused connects.'''
    session = requests.Session()
    session.headers['Connection'] = 'close'
    retry = Retry(total=3, connect=3, read=3, status=0, backoff_factor=0.2)
    session.mount('http://', HTTPAdapter(max_retries=retry))
    session.mount('https://', HTTPAdapter(max_retries=retry))
    return session


def stack_credential(name: str) -> str:
    '''A value the stack generated (`CONTRACT_PASSWORD`, `JWT_SECRET_KEY`, ...).'''
    for line in Path(os.environ['AUTHZ_CREDENTIALS_FILE']).read_text().splitlines():
        key, _, value = line.partition('=')
        if key == name:
            return value
    raise LookupError(f'no {name} in AUTHZ_CREDENTIALS_FILE')


def _admin_password() -> str:
    if os.environ.get('AUTHZ_ADMIN_PASSWORD'):
        return os.environ['AUTHZ_ADMIN_PASSWORD']
    return stack_credential('CONTRACT_PASSWORD')


def bearer(token: str) -> requests.Session:
    session = new_session()
    session.headers['Authorization'] = f'Bearer {token}'
    return session


def password_session(username: str, password: str) -> requests.Session:
    '''Signs every request in with the X-Username / X-Password headers.'''
    session = new_session()
    session.headers.update({'X-Username': username, 'X-Password': password})
    return session


def mint_token(identity: str, user_claims: dict, with_iat: bool = True) -> str:
    '''An access token signed with the stack's JWT key, encoded by the
    flask-jwt-extended the web app runs, with the given identity and claims.
    Mints tokens in the shapes older code issued, which today's code no
    longer does (a session with no `user_id`), and render tokens, which go
    only to the renderer. Without `with_iat` the token has no `iat` and no
    `nbf`, which the library never omits but PyJWT accepts.'''
    # pylint: disable=import-outside-toplevel
    import jwt
    from flask_jwt_extended.tokens import encode_access_token

    if not with_iat:
        payload = {
            'jti': secrets.token_hex(16),
            'exp': datetime.now(timezone.utc) + timedelta(days=365),
            'identity': identity,
            'fresh': False,
            'type': 'access',
            'user_claims': user_claims,
        }
        token = jwt.encode(payload, stack_credential('JWT_SECRET_KEY'), 'HS256')
        return token.decode() if isinstance(token, bytes) else token
    return encode_access_token(
        identity=identity,
        secret=stack_credential('JWT_SECRET_KEY'),
        algorithm='HS256',
        expires_delta=timedelta(days=365),
        fresh=False,
        user_claims=user_claims,
        csrf=True,
        identity_claim_key='identity',
        user_claims_key='user_claims',
    )


def login_session_cookie(user_id: int) -> requests.Session:
    '''A browser holding a flask-login session for account `user_id`, signed
    with the stack's session key the way Flask signs its session cookie.'''
    # pylint: disable=import-outside-toplevel
    from flask import Flask
    from flask.sessions import SecureCookieSessionInterface

    app = Flask('authz-session-cookie')
    app.secret_key = stack_credential('DEFAULT_SECRET_KEY')
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    session = new_session()
    # flask-login 0.4 keeps the account id under `user_id`.
    session.cookies.set('session', serializer.dumps({'user_id': str(user_id)}))
    return session


def _docker(container: str, args: list, stdin: str = '') -> str:
    result = subprocess.run(
        ['docker', 'exec', '-i', container, *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, (container, args, result.stderr[-2000:])
    return result.stdout


@dataclass
class Stack:
    base_url: str
    admin: requests.Session
    _users: dict = field(default_factory=dict, repr=False)
    created_users: set = field(default_factory=set, repr=False)
    created_dashboards: set = field(default_factory=set, repr=False)
    _admin_bearer: requests.Session | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> Stack:
        base_url = os.environ['AUTHZ_BASE_URL'].rstrip('/')
        host = urlparse(base_url).hostname
        if host not in LOOPBACK_HOSTS:
            raise RuntimeError(f'AUTHZ_BASE_URL must be a loopback stack, not {host!r}')
        admin = new_session()
        response = admin.post(
            f'{base_url}/api2/authentication/login',
            params={'set_cookie': 'true'},
            json={
                'email': os.environ['AUTHZ_ADMIN_USERNAME'],
                'password': _admin_password(),
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return cls(base_url, admin)

    def request(self, session: requests.Session, method: str, path: str, body=None):
        kwargs = {'timeout': TIMEOUT_SECONDS, 'allow_redirects': False}
        if body is not None:
            kwargs['data'] = json.dumps(body)
            kwargs['headers'] = {'Content-Type': 'application/json'}
        return session.request(method, self.base_url + path, **kwargs)

    def admin_json(self, method: str, path: str, body=None):
        response = self.request(self.admin, method, path, body)
        assert response.status_code < 300, (
            method,
            path,
            response.status_code,
            response.text[:500],
        )
        return response.json() if response.content else None

    @property
    def project(self) -> str:
        return os.environ.get('AUTHZ_PROJECT') or DEFAULT_PROJECT

    def sql(self, query: str, **params) -> list:
        '''Runs `query` in the stack's database; `:'name'` in it is `params[name]`
        as a quoted literal. Returns the result rows as tuples of strings.'''
        args = ['psql', '-U', 'postgres', '-d', DATABASE, '-v', 'ON_ERROR_STOP=1']
        args += ['-q', '-A', '-t', '-F', _FIELD_SEPARATOR]
        for name, value in params.items():
            args += ['-v', f'{name}={value}']
        output = _docker(f'{self.project}-postgres-1', args, query)
        return [tuple(line.split(_FIELD_SEPARATOR)) for line in output.splitlines()]

    def rewrite_account(
        self, uri: str, username: str, status_id: int = ACTIVE, invite: str = ''
    ) -> None:
        '''Sets an account's username, status and invitation token in the
        database, making accounts that only code before WP-0k's checks could:
        a case-only twin, or a pending invitation equal to a registered account
        ignoring case. The token column is not nullable; empty means none.'''
        self.sql(
            'UPDATE "user" SET username = :\'username\', status_id = :\'status\', '
            'reset_password_token = :\'invite\' WHERE id = :\'id\';',
            username=username,
            status=status_id,
            invite=invite,
            id=uri.rsplit('/', 1)[1],
        )

    def mail(self) -> list:
        '''Every message the stack's mail sink holds, oldest first, as
        `{'to': [address, ...], 'subject': str, 'links': [url, ...]}`; links are
        the `href` targets and bare URLs in the message, in order, deduplicated.'''
        script = (
            'import json, re, requests\n'
            "api = 'http://mailpit:8025/api/v1'\n"
            "listing = requests.get(api + '/messages', timeout=30).json()\n"
            'out = []\n'
            "for summary in reversed(listing['messages']):\n"
            "    message = requests.get(api + '/message/' + summary['ID'], timeout=30)\n"
            '    message = message.json()\n'
            "    body = (message.get('HTML') or '') + ' ' + (message.get('Text') or '')\n"
            '    links = re.findall(r\'href="([^"]*)"|(https?://[^\\s"<>]+)\', body)\n'
            '    links = [a or b for a, b in links]\n'
            "    out.append({'to': [to['Address'] for to in message['To']],\n"
            "                'subject': message['Subject'],\n"
            "                'links': list(dict.fromkeys(links))})\n"
            'print(json.dumps(out))\n'
        )
        output = _docker(f'{self.project}-web-1', ['python', '-'], script)
        return json.loads(output.strip().splitlines()[-1])

    def clear_mail(self) -> None:
        script = (
            'import requests\n'
            "requests.delete('http://mailpit:8025/api/v1/messages', timeout=30)"
            '.raise_for_status()\n'
        )
        _docker(f'{self.project}-web-1', ['python', '-'], script)

    def signed_in_as(self, session: requests.Session) -> str:
        '''The URI of the user the page layout says is signed in, or the
        outcome of the page request (`login` when anonymous) when it is not
        the overview page.'''
        response = self.request(session, 'GET', WHOAMI_PAGE)
        if outcome(response) != 'page:overviewPage':
            return outcome(response)
        user = json.loads(_BACKEND_JSON.search(response.text).group(1))['user']
        return f'/api2/user/{user["id"]}'

    def login(self, username: str, password: str, set_cookie: bool = False):
        '''`POST /api2/authentication/login` from a fresh session; returns the
        session (holding any cookie set) and the response.'''
        session = new_session()
        response = self.request(
            session,
            'POST',
            '/api2/authentication/login'
            + ('?set_cookie=true' if set_cookie else '?set_cookie=false'),
            {'email': username, 'password': password, 'remember_me': False},
        )
        return session, response

    def create_account(self, username: str, password: str) -> str:
        '''Creates an active account named exactly `username`, with no roles,
        through the admin API; returns its URI.'''
        response = self.request(
            self.admin,
            'POST',
            '/api2/user',
            {
                'username': username,
                'firstName': 'Authz',
                'lastName': 'Account',
                'phoneNumber': '',
                'status': 'active',
            },
        )
        assert response.status_code < 300, (username, response.text[:500])
        uri = response.json()['$uri']
        self.created_users.add(uri)
        self.admin_json('POST', f'{uri}/password', {'newPassword': password})
        return uri

    def admin_bearer(self) -> requests.Session:
        '''The admin signed in by an `Authorization` header instead of the
        cookie: requests matches cookies to a request's `Host` header, so a
        request with a forged Host carries no cookie.'''
        if self._admin_bearer is None:
            _, response = self.login(
                os.environ['AUTHZ_ADMIN_USERNAME'], _admin_password()
            )
            assert response.status_code == 200, response.text[:300]
            self._admin_bearer = bearer(response.json()['access_token'])
        return self._admin_bearer

    def create_dashboard(self, slug: str, headers=None, path_prefix: str = '') -> dict:
        '''Creates an empty dashboard as admin, sending `headers` with the
        request and `path_prefix` before its path; returns the dashboard.'''
        response = self.admin_bearer().post(
            f'{self.base_url}{path_prefix}/api2/dashboard',
            json={'slug': slug, 'specification': EMPTY_DASHBOARD},
            headers=headers or {},
            timeout=TIMEOUT_SECONDS,
        )
        assert response.status_code < 300, (slug, response.text[:500])
        dashboard = response.json()
        self.created_dashboards.add(dashboard['$uri'])
        return dashboard

    def patch_user(self, uri: str, **changes):
        '''A full-object `PATCH /api2/user/<id>` as admin, keeping every field
        but `changes`; returns the response.'''
        user = self.admin_json('GET', uri)
        body = {
            '$uri': uri,
            'username': user['username'],
            'firstName': user['firstName'],
            'lastName': user['lastName'],
            'phoneNumber': user['phoneNumber'],
            'status': user['status'],
            'acls': [],
            'apiTokens': [],
            'roles': [role['$uri'] for role in user['roles']],
            'groups': [],
        }
        body.update(changes)
        return self.request(self.admin, 'PATCH', uri, body)

    def roles_by_name(self) -> dict:
        return {
            role['name']: role['$uri']
            for role in self.admin_json('GET', '/api2/role?per_page=100')
        }

    def find_user(self, username: str):
        where = json.dumps({'username': username})
        found = self.admin_json('GET', f'/api2/user?where={where}')
        return found[0] if found else None

    def ensure_user(
        self, local_part: str, role_names=(), group_uris=()
    ) -> requests.Session:
        '''Creates or resets `<local_part>@authz.invalid` to hold exactly `role_names`.'''
        username = f'{local_part[:36]}@{USER_DOMAIN}'
        user = self.find_user(username)
        fields = {
            'username': username,
            'firstName': 'Authz',
            'lastName': local_part[:50],
            'phoneNumber': '',
        }
        if user is None:
            user = self.admin_json('POST', '/api2/user', {**fields, 'status': 'active'})
        uri = user['$uri']
        self.created_users.add(uri)
        password = secrets.token_urlsafe(18)
        self.admin_json('POST', f'{uri}/password', {'newPassword': password})
        roles = self.roles_by_name()
        self.admin_json(
            'PATCH',
            uri,
            {
                '$uri': uri,
                **fields,
                'status': 'active',
                'acls': [],
                'apiTokens': [],
                'roles': [roles[name] for name in role_names],
                'groups': list(group_uris),
            },
        )
        session = new_session()
        session.headers.update({'X-Username': username, 'X-Password': password})
        session.user_uri = uri  # type: ignore[attr-defined]
        return session

    def role_user(self, role_name: str) -> requests.Session:
        if role_name not in self._users:
            self._users[role_name] = self.ensure_user(f'role-{role_name}', [role_name])
        return self._users[role_name]

    def session_for(self, principal: str) -> requests.Session:
        if principal == 'anonymous':
            return new_session()
        assert principal.startswith('role:'), principal
        return self.role_user(principal[len('role:') :])

    def delete_group_named(self, name: str) -> None:
        for group in self.admin_json('GET', '/api2/group?per_page=100'):
            if group['name'] == name:
                self.admin_json('DELETE', group['$uri'])

    def cleanup(self, keep_users=(), keep_dashboards=()) -> None:
        '''Deletes every dashboard this run created, then every user it created
        or reset, except those in `keep_*`. Saved queries go with their users
        (user_query_session.user_id cascades).'''
        for uri in sorted(set(self.created_dashboards) - set(keep_dashboards)):
            response = self.request(self.admin, 'DELETE', uri)
            assert response.status_code in (204, 404), (uri, response.status_code)
            self.created_dashboards.discard(uri)
        for uri in sorted(set(self.created_users) - set(keep_users)):
            response = self.request(self.admin, 'DELETE', uri)
            assert response.status_code in (204, 404), (uri, response.status_code)
            self.created_users.discard(uri)
        if not keep_users:
            self._users.clear()
