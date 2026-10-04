"""Checks on the Druid Compose setups in druid_setup/.

Run with: uv run --no-project --with pytest pytest tests/druid_setup
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

DRUID_SETUP = Path(__file__).resolve().parents[2] / 'druid_setup'

needs_docker = pytest.mark.skipif(
    shutil.which('docker') is None, reason='docker CLI not available'
)

# Dummy values only. The process environment is replaced, so nothing from the
# caller's shell or an operator's druid_setup/.env leaks in.
BASE_ENV = {
    'DRUID_POSTGRES_PASSWORD': 'test-druid-postgres-password',
    'DRUID_MASTER_HOST': '10.0.0.10',
}

# (directory, env file the Makefile passes, compose file)
SETUPS = [
    ('single', 'environment/common.env', 'docker-compose.yml'),
    ('cluster', 'cluster.env', 'docker-compose-master.yml'),
    ('cluster', 'cluster.env', 'docker-compose-data.yml'),
    ('cluster', 'cluster.env', 'docker-compose-query.yml'),
]
# The files that run the metadata store and the coordinator.
METADATA_SETUPS = SETUPS[:2]


def setup_id(setup):
    return f'{setup[0]}/{setup[2]}'


PASSWORD_PROVIDER = {'type': 'environment', 'variable': 'DRUID_POSTGRES_PASSWORD'}


def render(tmp_path, setup, env=None, unset=()):
    directory, env_file, compose_file = setup
    values = {**BASE_ENV, **(env or {})}
    for key in unset:
        values.pop(key, None)
    return subprocess.run(
        [
            'docker', 'compose', '--env-file', env_file, '-f', compose_file,
            'config', '--format', 'json',
        ],
        capture_output=True,
        text=True,
        cwd=DRUID_SETUP / directory,
        env={
            'PATH': '/usr/bin:/bin:/usr/local/bin',
            'HOME': str(tmp_path),
            **values,
        },
        check=False,
    )


def config(tmp_path, setup, env=None):
    result = render(tmp_path, setup, env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def env_file_values(path):
    values = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key] = value
    return values


def test_no_default_password_anywhere():
    offenders = [
        str(path.relative_to(DRUID_SETUP))
        for path in DRUID_SETUP.rglob('*')
        if path.is_file() and 'FoolishPassword' in path.read_text(errors='ignore')
    ]
    assert offenders == []


@pytest.mark.parametrize(
    'common_env', ['single/environment/common.env', 'cluster/environment/common.env']
)
def test_druid_reads_metadata_password_from_environment(common_env):
    values = env_file_values(DRUID_SETUP / common_env)
    provider = json.loads(values['druid_metadata_storage_connector_password'])
    assert provider == PASSWORD_PROVIDER


@needs_docker
@pytest.mark.parametrize('setup', METADATA_SETUPS, ids=setup_id)
@pytest.mark.parametrize('value', ['unset', 'empty'])
def test_refuses_to_render_without_metadata_password(tmp_path, setup, value):
    if value == 'unset':
        result = render(tmp_path, setup, unset=['DRUID_POSTGRES_PASSWORD'])
    else:
        result = render(tmp_path, setup, env={'DRUID_POSTGRES_PASSWORD': ''})
    assert result.returncode != 0
    assert 'required variable DRUID_POSTGRES_PASSWORD' in result.stderr


@needs_docker
@pytest.mark.parametrize('setup', METADATA_SETUPS, ids=setup_id)
def test_password_reaches_postgres_and_coordinator(tmp_path, setup):
    services = config(tmp_path, setup)['services']
    password = BASE_ENV['DRUID_POSTGRES_PASSWORD']
    assert services['postgres']['environment']['POSTGRES_PASSWORD'] == password
    coordinator = services['coordinator']['environment']
    assert coordinator['DRUID_POSTGRES_PASSWORD'] == password
    # Druid's entrypoint echoes every runtime property into the container
    # log, so the password must not be one.
    assert password not in coordinator.get(
        'druid_metadata_storage_connector_password', ''
    )
