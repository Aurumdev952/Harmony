'''`config.settings` is a facade over `harmony.core.settings` that its readers
cannot tell apart from the module it replaced (INV-1).

`legacy/config_settings_ea33d9d.py` is `config/settings.py` as of ea33d9d, before
the facade. Each case imports it and the facade in fresh interpreters with the same
environment and compares attributes, the warnings logged, `getenv` and
`require_secret`.
'''

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LEGACY = Path(__file__).resolve().parent / 'legacy' / 'config_settings_ea33d9d.py'
KEY = '9f2c4e6a8b0d1f3e5a7c9b1d3f5e7a9c'
JWT_KEY = '0123456789abcdef0123456789abcdef'

ATTRIBUTES = (
    'DEFAULT_SECRET_KEY',
    'NOREPLY_EMAIL',
    'SUPPORT_EMAIL',
    'REDIS_HOST',
    'HASURA_HOST',
    'DRUID_HOST',
)
# WP-1h deletes these from config.settings; they are outside the facade's
# contract, so the comparison ignores them on both sides.
URLBOX_ERA = ('RENDERBOT_EMAIL', 'URLBOX_API_KEY')
SETTINGS = (
    'DEFAULT_SECRET_KEY',
    'DRUID_HOST',
    'NOREPLY_EMAIL',
    'SUPPORT_EMAIL',
    'REDIS_HOST',
    'HASURA_HOST',
    'OBJECT_STORAGE_ALIAS',
    'MAPBOX_ACCESS_TOKEN',
    'RENDERBOT_EMAIL',
    'URLBOX_API_KEY',
    'JWT_SECRET_KEY',
    'PARITY_PROBE',
)

PROBE = '''
import importlib.util, json, logging, sys

from log import LOG

warnings = []


class Capture(logging.Handler):
    def emit(self, record):
        warnings.append([record.levelname, record.getMessage()])


LOG.addHandler(Capture())


def outcome(call):
    try:
        return {'value': call()}
    except Exception as error:  # noqa: BLE001
        return {'error': type(error).__name__, 'message': str(error)}


def load():
    if sys.argv[1] == 'facade':
        from config import settings
        return settings
    spec = importlib.util.spec_from_file_location('legacy_settings', sys.argv[2])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    module = load()
except Exception as error:  # noqa: BLE001
    result = {'import': {'error': type(error).__name__, 'message': str(error)}}
else:
    names = json.loads(sys.argv[3])
    result = {
        'import': {},
        'attributes': {n: getattr(module, n, '<absent>') for n in names},
        'getenv': outcome(lambda: module.getenv('PARITY_PROBE')),
        'getenv_default': outcome(lambda: module.getenv('PARITY_PROBE', 'd')),
        'require_secret': outcome(lambda: module.require_secret('JWT_SECRET_KEY')),
    }
result['warnings'] = warnings
print(json.dumps(result))
'''


def _run(kind: str, environment: dict[str, str]) -> dict:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in SETTINGS and key != 'PYTHONPATH'
    }
    env.update(environment)
    env['ZEN_ENV'] = 'harmony_demo'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    proc = subprocess.run(
        [sys.executable, '-c', PROBE, kind, str(LEGACY), json.dumps(ATTRIBUTES)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    result['warnings'] = [
        warning
        for warning in result['warnings']
        if not any(name in warning[1] for name in URLBOX_ERA)
    ]
    return result


REQUIRED = {'DEFAULT_SECRET_KEY': KEY, 'DRUID_HOST': 'http://druid.invalid'}

MATCHING = {
    'minimal': REQUIRED,
    'everything set': {
        **REQUIRED,
        'NOREPLY_EMAIL': 'noreply@example.invalid',
        'SUPPORT_EMAIL': 'support@example.invalid',
        'REDIS_HOST': 'redis',
        'HASURA_HOST': 'http://hasura:8080',
        'RENDERBOT_EMAIL': 'bot@example.invalid',
        'URLBOX_API_KEY': 'not-a-key',
        'JWT_SECRET_KEY': JWT_KEY,
        'PARITY_PROBE': 'x',
    },
    'everything empty': {
        **REQUIRED,
        'DRUID_HOST': '',
        'NOREPLY_EMAIL': '',
        'SUPPORT_EMAIL': '',
        'REDIS_HOST': '',
        'HASURA_HOST': '',
        'RENDERBOT_EMAIL': '',
        'URLBOX_API_KEY': '',
        'JWT_SECRET_KEY': '',
        'PARITY_PROBE': '',
    },
    'whitespace and padding': {
        'DEFAULT_SECRET_KEY': f'  {KEY}\n',
        'DRUID_HOST': ' http://druid.invalid ',
        'SUPPORT_EMAIL': ' ',
        'REDIS_HOST': ' redis ',
        'JWT_SECRET_KEY': ' changeme ',
        'PARITY_PROBE': ' ',
    },
    'json-like and null strings': {
        **REQUIRED,
        'NOREPLY_EMAIL': 'null',
        'HASURA_HOST': '{"a": 1}',
        'PARITY_PROBE': 'None',
    },
    'default secret key unset': {'DRUID_HOST': 'http://druid.invalid'},
    'default secret key changeme': {**REQUIRED, 'DEFAULT_SECRET_KEY': 'ChangeMe'},
}


@pytest.mark.parametrize('environment', MATCHING.values(), ids=MATCHING.keys())
def test_facade_matches_the_module_it_replaced(environment):
    assert _run('facade', environment) == _run('legacy', environment)


def test_missing_druid_host_stops_the_import_before_any_warning():
    # The recorded difference: KeyError('DRUID_HOST'), raised after the optional
    # settings had logged, becomes a RuntimeError naming every problem, raised
    # before anything is logged. No reader catches either exception.
    legacy = _run('legacy', {'DEFAULT_SECRET_KEY': KEY})
    facade = _run('facade', {'DEFAULT_SECRET_KEY': KEY})

    assert legacy['import'] == {'error': 'KeyError', 'message': "'DRUID_HOST'"}
    assert len(legacy['warnings']) == 4
    assert facade == {
        'import': {
            'error': 'RuntimeError',
            'message': 'DRUID_HOST is not set; refusing to start.',
        },
        'warnings': [],
    }


def test_refused_secret_and_missing_druid_host_are_reported_together():
    legacy = _run('legacy', {'DEFAULT_SECRET_KEY': ''})
    facade = _run('facade', {'DEFAULT_SECRET_KEY': ''})

    assert legacy['import']['error'] == facade['import']['error'] == 'RuntimeError'
    assert facade['import']['message'] == (
        legacy['import']['message'] + '\nDRUID_HOST is not set; refusing to start.'
    )
    assert facade['warnings'] == legacy['warnings'] == []


def test_facade_values_come_from_core_settings():
    facade = _run('facade', {**REQUIRED, 'SUPPORT_EMAIL': 'support@example.invalid'})

    assert facade['attributes']['SUPPORT_EMAIL'] == 'support@example.invalid'
    assert facade['attributes']['DEFAULT_SECRET_KEY'] == KEY


DEPLOYMENT_PROBE = '''
import json, logging

from log import LOG

warnings = []


class Capture(logging.Handler):
    def emit(self, record):
        warnings.append(record.getMessage())


LOG.addHandler(Capture())
from config.{code} import general, ui

print(json.dumps({{
    'OBJECT_STORAGE_ALIAS': general.OBJECT_STORAGE_ALIAS,
    'MAPBOX_ACCESS_TOKEN': ui.MAPBOX_ACCESS_TOKEN,
    'warnings': [w for w in warnings if 'OBJECT_STORAGE' in w or 'MAPBOX' in w],
}}))
'''


def _deployment(code: str, environment: dict[str, str]) -> dict:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in SETTINGS and key != 'PYTHONPATH'
    }
    env.update({**REQUIRED, **environment, 'ZEN_ENV': 'harmony_demo'})
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    proc = subprocess.run(
        [sys.executable, '-c', DEPLOYMENT_PROBE.format(code=code)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize('code', ['harmony_demo', 'template'])
def test_deployment_modules_read_settings_and_warn_when_unset(code):
    assert _deployment(code, {}) == {
        'OBJECT_STORAGE_ALIAS': None,
        'MAPBOX_ACCESS_TOKEN': None,
        'warnings': [
            'Environment variable OBJECT_STORAGE_ALIAS not set',
            'Environment variable MAPBOX_ACCESS_TOKEN not set',
        ],
    }


@pytest.mark.parametrize('code', ['harmony_demo', 'template'])
def test_deployment_modules_pass_values_through(code):
    environment = {'OBJECT_STORAGE_ALIAS': 'minio', 'MAPBOX_ACCESS_TOKEN': 'pk.test'}

    assert _deployment(code, environment) == {**environment, 'warnings': []}
