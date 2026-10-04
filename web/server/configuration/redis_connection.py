from os import getenv
from typing import Optional
from urllib.parse import quote

REDIS_PORT = 6379


def require_redis_password() -> str:
    '''REDIS_PASSWORD, for when REDIS_HOST names a Redis server (SEC-3).'''
    password = getenv('REDIS_PASSWORD')
    if not password:
        raise RuntimeError(
            'REDIS_PASSWORD is unset or empty but REDIS_HOST is set; refusing to start. '
            'Set REDIS_PASSWORD to the password Redis runs with (requirepass).'
        )
    return password


def get_redis_password() -> Optional[str]:
    '''REDIS_PASSWORD, required when REDIS_HOST is set and optional otherwise.'''
    if getenv('REDIS_HOST'):
        return require_redis_password()
    return getenv('REDIS_PASSWORD') or None


def build_redis_url(host: str, password: str) -> str:
    return f'redis://:{quote(password, safe="")}@{host}:{REDIS_PORT}/'
