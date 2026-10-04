'''Talks to a live Harmony stack for the HTTP layer of the authorisation suite.

Every seeded role gets one user, `role-<role>@authz.invalid`, created (or
reset) through the admin API with a password generated for this run and never
written anywhere. Requests authenticate with X-Username / X-Password headers,
which load the account's needs without JWT narrowing, like the `role:<name>`
principals of the pure layer.
'''

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TIMEOUT_SECONDS = 120
USER_DOMAIN = 'authz.invalid'
_BUNDLE = re.compile(r'/([A-Za-z]+)\.bundle\.js')


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
    '''A session that retries idempotent requests whose pooled keep-alive
    connection the server closed between requests.'''
    session = requests.Session()
    retry = Retry(total=3, connect=3, read=3, status=0, backoff_factor=0.2)
    session.mount('http://', HTTPAdapter(max_retries=retry))
    session.mount('https://', HTTPAdapter(max_retries=retry))
    return session


def _admin_password() -> str:
    if os.environ.get('AUTHZ_ADMIN_PASSWORD'):
        return os.environ['AUTHZ_ADMIN_PASSWORD']
    for line in Path(os.environ['AUTHZ_CREDENTIALS_FILE']).read_text().splitlines():
        key, _, value = line.partition('=')
        if key == 'CONTRACT_PASSWORD':
            return value
    raise LookupError('no admin password in AUTHZ_CREDENTIALS_FILE')


@dataclass
class Stack:
    base_url: str
    admin: requests.Session
    _users: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls) -> Stack:
        base_url = os.environ['AUTHZ_BASE_URL'].rstrip('/')
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
