"""Checks on the Hasura service in the rendered Compose configuration (WP-0a).

Run with: uv run --with pytest pytest tests/infra/test_compose_hasura.py
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which('docker') is None, reason='docker CLI not available'
)

HASURA_IMAGE = (
    'hasura/graphql-engine:v2.45.8-ce.cli-migrations-v2'
    '@sha256:18b39122f207afa4fe7116acaa6484ddac69c2160fde0571e3a27abf924e0bec'
)

# Dummy values only. Passing an explicit env file stops Compose from reading
# the repository's real `.env`. The other secrets are here so these tests
# keep rendering once WP-0b makes them required too.
DUMMY_ENV = {
    'ZEN_ENV': 'harmony_demo',
    'DRUID_HOST': 'http://druid.invalid',
    'DATABASE_URL': 'postgresql://u:p@db.invalid:5432/harmony',
    'MC_CONFIG_PATH': '/tmp/mc',
    'DATA_PATH': '/tmp/data',
    'NGINX_VHOST': '/tmp/nginx_vhost',
    'DEFAULT_SECRET_KEY': 'test-session-key',
    'JWT_SECRET_KEY': 'test-jwt-key',
    'REDIS_PASSWORD': 'testredispassword',
    'HASURA_ADMIN_SECRET': 'test-hasura-admin-secret',
}

OVERLAYS = {
    'base': [],
    'prod': ['docker-compose.prod.yaml'],
    'dev': ['docker-compose.dev.yaml'],
    'local': ['docker-compose.local.yaml'],
}


def render_compose(tmp_path, overlays, env=None, unset=()):
    values = {**DUMMY_ENV, **(env or {})}
    for key in unset:
        values.pop(key)
    env_file = tmp_path / 'hasura-test.env'
    env_file.write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
    args = ['docker', 'compose', '--env-file', str(env_file)]
    for name in ['docker-compose.yaml', *overlays]:
        args += ['-f', str(REPO / name)]
    return subprocess.run(
        [*args, 'config', '--format', 'json'],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={'PATH': '/usr/bin:/bin:/usr/local/bin', 'HOME': str(tmp_path)},
        check=False,
    )


def compose_services(tmp_path, overlays):
    result = render_compose(tmp_path, overlays)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)['services']


@pytest.mark.parametrize('overlay', OVERLAYS)
def test_hasura_publishes_no_port(tmp_path, overlay):
    hasura = compose_services(tmp_path, OVERLAYS[overlay])['hasura']
    assert not hasura.get('ports')


@pytest.mark.parametrize('overlay', OVERLAYS)
@pytest.mark.parametrize('value', [None, ''], ids=['unset', 'empty'])
def test_refuses_to_render_without_admin_secret(tmp_path, overlay, value):
    if value is None:
        result = render_compose(
            tmp_path, OVERLAYS[overlay], unset=['HASURA_ADMIN_SECRET']
        )
    else:
        result = render_compose(
            tmp_path, OVERLAYS[overlay], {'HASURA_ADMIN_SECRET': value}
        )
    assert result.returncode != 0
    assert 'HASURA_ADMIN_SECRET must be set' in result.stderr


@pytest.mark.parametrize('overlay', OVERLAYS)
def test_hasura_and_web_share_the_admin_secret(tmp_path, overlay):
    services = compose_services(tmp_path, OVERLAYS[overlay])
    secret = DUMMY_ENV['HASURA_ADMIN_SECRET']
    hasura_env = services['hasura']['environment']
    assert hasura_env['HASURA_GRAPHQL_ADMIN_SECRET'] == secret
    assert services['web']['environment']['HASURA_ADMIN_SECRET'] == secret


def test_hasura_is_pinned_with_only_graphql_and_metadata_apis(tmp_path):
    hasura = compose_services(tmp_path, [])['hasura']
    assert hasura['image'] == HASURA_IMAGE
    assert hasura['environment']['HASURA_GRAPHQL_ENABLE_CONSOLE'] == 'false'
    assert hasura['environment']['HASURA_GRAPHQL_DEV_MODE'] == 'false'
    assert hasura['environment']['HASURA_GRAPHQL_ENABLED_APIS'] == 'graphql,metadata'
