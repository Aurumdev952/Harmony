import os

import pytest
from flask import Flask
from flask_caching import Cache
from redis import Redis

# config/settings.py reads these at import time; the values are test-only placeholders.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-web-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('ZEN_ENV', 'harmony_demo')

# pylint: disable=wrong-import-position
from web.server.configuration.celery import DEFAULT_BROKER_URL, get_broker_url
from web.server.configuration.flask import FlaskConfiguration

# Every character that has a meaning in a URL's authority or path.
AWKWARD_PASSWORD = 'p@ss:w/rd%#?&= x'


def _redis_password_in(url: str) -> str:
    return Redis.from_url(url).connection_pool.connection_kwargs['password']


@pytest.fixture(name='redis_env')
def fixture_redis_env(monkeypatch):
    for name in ('REDIS_HOST', 'REDIS_PASSWORD', 'BROKER_URL'):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_broker_url_carries_the_password(redis_env):
    redis_env.setenv('REDIS_HOST', 'redis')
    redis_env.setenv('REDIS_PASSWORD', AWKWARD_PASSWORD)

    url = get_broker_url()

    assert url.endswith('@redis:6379/')
    assert _redis_password_in(url) == AWKWARD_PASSWORD


@pytest.mark.parametrize('password', [None, ''])
def test_broker_refuses_a_configured_redis_without_password(redis_env, password):
    redis_env.setenv('REDIS_HOST', 'redis')
    if password is not None:
        redis_env.setenv('REDIS_PASSWORD', password)

    with pytest.raises(RuntimeError, match='REDIS_PASSWORD'):
        get_broker_url()


def test_explicit_broker_url_is_used_as_given(redis_env):
    redis_env.setenv('BROKER_URL', 'redis://:secret@broker:6379/0')

    assert get_broker_url() == 'redis://:secret@broker:6379/0'


@pytest.mark.usefixtures('redis_env')
def test_no_redis_configured_keeps_the_default_broker():
    assert get_broker_url() == DEFAULT_BROKER_URL


def test_flask_cache_client_carries_the_password(redis_env):
    redis_env.setenv('REDIS_HOST', 'redis')
    redis_env.setenv('REDIS_PASSWORD', AWKWARD_PASSWORD)

    cache_config = FlaskConfiguration().CACHES['default']
    # Explicit root_path: Flask 1.0 cannot locate a module loaded by pytest's rewrite hook.
    app = Flask('tests.web', root_path=os.path.dirname(__file__))
    cache = Cache(app, config=cache_config)

    assert cache_config['CACHE_TYPE'] == 'RedisCache'
    # pylint: disable=protected-access
    client = cache.cache._write_client
    assert client.connection_pool.connection_kwargs['password'] == AWKWARD_PASSWORD


@pytest.mark.parametrize('password', [None, ''])
def test_flask_refuses_a_configured_redis_without_password(redis_env, password):
    redis_env.setenv('REDIS_HOST', 'redis')
    if password is not None:
        redis_env.setenv('REDIS_PASSWORD', password)

    with pytest.raises(RuntimeError, match='REDIS_PASSWORD'):
        FlaskConfiguration()


@pytest.mark.usefixtures('redis_env')
def test_flask_without_redis_needs_no_password():
    assert FlaskConfiguration().CACHES['default']['CACHE_TYPE'] == 'FileSystemCache'
