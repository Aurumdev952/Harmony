'''`harmony.core.settings`: typed process settings read from the environment
(BE-2), refusing default secrets at load (SEC-3).'''

from __future__ import annotations

import pydantic
import pytest

from harmony.core import settings as core_settings
from harmony.core.settings import Settings, get_settings, load_settings

REAL_KEY = '9f2c4e6a8b0d1f3e5a7c9b1d3f5e7a9c'


@pytest.fixture(autouse=True)
def environ(monkeypatch):
    '''An environment holding only the two required settings.'''
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setenv('DEFAULT_SECRET_KEY', REAL_KEY)
    monkeypatch.setenv('DRUID_HOST', 'http://druid.invalid')
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


@pytest.mark.parametrize(
    'secret_key',
    [None, '', '   ', 'changeme', 'CHANGEME', ' ChangeMe\n'],
    ids=['unset', 'empty', 'blank', 'changeme', 'upper', 'padded'],
)
def test_refuses_a_default_secret_key(environ, secret_key):
    if secret_key is None:
        environ.delenv('DEFAULT_SECRET_KEY')
    else:
        environ.setenv('DEFAULT_SECRET_KEY', secret_key)

    with pytest.raises(RuntimeError) as raised:
        load_settings()

    message = str(raised.value)
    assert 'DEFAULT_SECRET_KEY' in message
    assert 'openssl rand -hex 32' in message
    # The ValidationError holds the raw input, which may be a secret: not chained.
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_keeps_a_real_key_verbatim_and_hidden(environ):
    padded = f' {REAL_KEY} '
    environ.setenv('DEFAULT_SECRET_KEY', padded)

    loaded = load_settings()

    assert loaded.DEFAULT_SECRET_KEY.get_secret_value() == padded
    assert REAL_KEY not in repr(loaded)
    assert REAL_KEY not in str(loaded)


def test_refuses_a_missing_druid_host_without_exposing_the_key(environ):
    environ.delenv('DRUID_HOST')

    with pytest.raises(RuntimeError) as raised:
        load_settings()

    assert str(raised.value) == 'DRUID_HOST is not set; refusing to start.'
    # A traceback must not reach the ValidationError, which holds the real key.
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert REAL_KEY not in str(raised.value)


def test_accepts_an_empty_druid_host_as_before(environ):
    # Compose passes DRUID_HOST=${DRUID_HOST}, which is '' when the host variable
    # is unset; config.settings accepted that, so refusing it could stop a deployment.
    environ.setenv('DRUID_HOST', '')

    assert load_settings().DRUID_HOST == ''


def test_reports_every_problem_at_once(environ):
    environ.setenv('DEFAULT_SECRET_KEY', 'changeme')
    environ.delenv('DRUID_HOST')

    with pytest.raises(RuntimeError) as raised:
        load_settings()

    assert 'DEFAULT_SECRET_KEY' in str(raised.value)
    assert 'DRUID_HOST' in str(raised.value)


def test_optional_settings_default_like_config_settings():
    loaded = load_settings()

    assert loaded.NOREPLY_EMAIL is None
    assert loaded.SUPPORT_EMAIL is None
    assert loaded.REDIS_HOST == ''
    assert loaded.HASURA_HOST is None
    assert loaded.OBJECT_STORAGE_ALIAS is None
    assert loaded.MAPBOX_ACCESS_TOKEN is None


@pytest.mark.parametrize(
    'name',
    [
        'NOREPLY_EMAIL',
        'SUPPORT_EMAIL',
        'REDIS_HOST',
        'HASURA_HOST',
        'OBJECT_STORAGE_ALIAS',
        'MAPBOX_ACCESS_TOKEN',
    ],
)
@pytest.mark.parametrize('value', ['', ' padded ', 'null', '{"a": 1}'])
def test_optional_settings_are_read_verbatim(environ, name, value):
    environ.setenv(name, value)

    assert getattr(load_settings(), name) == value


def test_names_are_case_sensitive(environ):
    environ.setenv('support_email', 'lower@example.invalid')

    assert load_settings().SUPPORT_EMAIL is None


def test_does_not_read_a_dotenv_file(environ, tmp_path):
    (tmp_path / '.env').write_text('DRUID_HOST=http://from-dotenv.invalid\n')
    environ.chdir(tmp_path)
    environ.delenv('DRUID_HOST')

    with pytest.raises(RuntimeError, match='DRUID_HOST'):
        load_settings()


def test_is_frozen():
    loaded = load_settings()

    with pytest.raises(pydantic.ValidationError):
        loaded.DRUID_HOST = 'http://elsewhere.invalid'


def test_get_settings_loads_once_per_process(environ):
    first = get_settings()
    environ.setenv('DRUID_HOST', 'http://changed.invalid')

    assert get_settings() is first
    assert get_settings().DRUID_HOST == 'http://druid.invalid'


def test_does_not_define_removed_or_logging_settings():
    # URLBOX_API_KEY and RENDERBOT_EMAIL went with urlbox (WP-1h); LOG_FORMAT and
    # LOG_LEVEL are read by log/ before settings load (WP-2g).
    for name in ('URLBOX_API_KEY', 'RENDERBOT_EMAIL', 'LOG_FORMAT', 'LOG_LEVEL'):
        assert name not in Settings.model_fields


@pytest.mark.parametrize(
    'value', ['', '  ', 'changeme', 'ChangeMe '], ids=['empty', 'blank', 'lc', 'mixed']
)
def test_refuse_default_secret_names_the_variable(value):
    with pytest.raises(ValueError) as raised:
        core_settings.refuse_default_secret('JWT_SECRET_KEY', value)

    assert 'JWT_SECRET_KEY' in str(raised.value)
    assert 'openssl rand -hex 32' in str(raised.value)


def test_refuse_default_secret_returns_a_real_value():
    assert core_settings.refuse_default_secret('X', f' {REAL_KEY}') == f' {REAL_KEY}'
