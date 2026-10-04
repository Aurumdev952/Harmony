from os import getenv
from typing import Optional
from urllib.parse import quote

REDIS_PORT = 6379


def get_redis_password() -> Optional[str]:
    '''REDIS_PASSWORD, required whenever REDIS_HOST names a Redis server (SEC-3).'''
    password = getenv('REDIS_PASSWORD') or None
    if getenv('REDIS_HOST') and not password:
        raise RuntimeError(
            'REDIS_PASSWORD is unset or empty but REDIS_HOST is set; refusing to start. '
            'Set REDIS_PASSWORD to the password Redis runs with (requirepass).'
        )
    return password


def build_redis_url(host: str, password: str) -> str:
    return f'redis://:{quote(password, safe="")}@{host}:{REDIS_PORT}/'
