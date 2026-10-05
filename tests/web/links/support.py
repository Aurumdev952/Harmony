"""Fakes and helpers for the mailed-link tests (see conftest.py)."""

import dataclasses
import logging
import re
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Iterator, List, Optional

from flask import Flask, g

# The deployment's configured origin (DEPLOYMENT_BASE_URL) in these tests.
ORIGIN = 'https://harmony.example.org'

# Request environs a caller controls. None of them may reach a mailed link.
HOSTILE_ENVIRONS = {
    'plain': {},
    'forged Host': {'HTTP_HOST': 'attacker.invalid'},
    'Host with userinfo': {'HTTP_HOST': 'real.org:@attacker.invalid'},
    'Host with port': {'HTTP_HOST': 'harmony.example.org:8443'},
    'forged SCRIPT_NAME': {'SCRIPT_NAME': '@attacker.invalid'},
    'SCRIPT_NAME prefix': {'SCRIPT_NAME': '/prefix'},
    'X-Forwarded-Host': {'HTTP_X_FORWARDED_HOST': 'attacker.invalid'},
    'plain http': {'wsgi.url_scheme': 'http'},
}


@dataclasses.dataclass
class FakeUser:
    id: int
    username: str
    first_name: str = 'Ada'
    last_name: str = 'Lovelace'
    is_authenticated: bool = True
    is_active: bool = True
    is_anonymous: bool = False
    reset_password_token: Optional[str] = None

    def get_id(self):
        return str(self.id)


INVITER = FakeUser(1, 'inviter@harmony.example.org')
USERS = {user.username: user for user in [INVITER]}


class RecordingMailer:
    def __init__(self):
        self.messages: List = []

    def send_email(self, message):
        self.messages.append(message)


class FakeUserManager:
    def __init__(self):
        self.db_adapter = SimpleNamespace(
            update_object=lambda obj, **fields: None, commit=lambda: None
        )

    @staticmethod
    def generate_token(user_id):
        return f'token-{user_id}'


@contextmanager
def request_as(
    app: Flask, environ: dict, username: str = '', path: str = '/api2/x'
) -> Iterator[None]:
    headers = {'X-Test-User': username} if username else {}
    with app.test_request_context(
        path, method='POST', headers=headers, environ_overrides=environ
    ):
        g.request_logger = logging.LoggerAdapter(logging.getLogger('tests.web'), {})
        yield


_LINK = re.compile(r'https?://[^\s"\'<>]+')


def mailed_links(message, marker: str) -> set:
    """Every URL in the message's text and HTML whose path contains `marker`."""
    text = f'{message.body}\n{message.html}'
    return {link for link in _LINK.findall(text) if marker in link}
