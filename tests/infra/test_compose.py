"""Checks on the rendered Compose configuration.

Run with: uv run --with pytest pytest tests/infra
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

# Dummy values only. An explicit env file stops Compose from reading the
# repository's real `.env`.
BASE_ENV = {
    'ZEN_ENV': 'harmony_demo',
    'DRUID_HOST': 'http://druid.invalid',
    'DATABASE_URL': 'postgresql://u:p@db.invalid:5432/harmony',
    'MC_CONFIG_PATH': '/tmp/mc',
    'DATA_PATH': '/tmp/data',
    'NGINX_VHOST': '/tmp/nginx_vhost',
    'DEFAULT_SECRET_KEY': 'test-session-key',
    'JWT_SECRET_KEY': 'test-jwt-key',
    'POSTGRES_PASSWORD': 'test-postgres-password',
    'POSTGRES_BIND_ADDRESS': '127.0.0.1',
    'MINIO_ROOT_USER': 'test-minio-user',
    'MINIO_ROOT_PASSWORD': 'test-minio-password',
    'MINIO_BIND_ADDRESS': '127.0.0.1',
    'REDIS_PASSWORD': 'testredispassword',
    'HASURA_ADMIN_SECRET': 'test-hasura-admin-secret',
}


def render(tmp_path, files, env=None, unset=()):
    values = {**BASE_ENV, **(env or {})}
    for key in unset:
        values.pop(key, None)
    env_file = tmp_path / 'test.env'
    env_file.write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
    args = ['docker', 'compose', '--env-file', str(env_file)]
    for name in files:
        args += ['-f', str(REPO / name)]
    return subprocess.run(
        [*args, 'config', '--format', 'json'],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={'PATH': '/usr/bin:/bin:/usr/local/bin', 'HOME': str(tmp_path)},
        check=False,
    )


def config(tmp_path, files, env=None):
    result = render(tmp_path, files, env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_pipeline_does_not_set_unread_postgres_db_uri(tmp_path):
    cfg = config(tmp_path, ['docker-compose.pipeline.yaml'])
    environment = cfg['services']['etl-pipeline']['environment']
    assert not any(key.startswith('POSTGRES_DB_URI') for key in environment)


@pytest.mark.parametrize(
    'files',
    [
        ['docker-compose.yaml', 'docker-compose.prod.yaml'],
        ['docker-compose.yaml', 'docker-compose.dev.yaml'],
        ['docker-compose.pipeline.yaml'],
        ['docker-compose.db.yaml'],
        ['docker-compose.minio.yaml'],
    ],
)
def test_no_environment_key_contains_a_colon(tmp_path, files):
    for name, service in config(tmp_path, files)['services'].items():
        bad = [key for key in service.get('environment', {}) if ':' in key]
        assert not bad, f'{name}: {bad}'


def published(cfg):
    return {
        name: service['ports']
        for name, service in cfg['services'].items()
        if service.get('ports')
    }


@pytest.mark.parametrize(
    'overlays',
    [[], ['docker-compose.prod.yaml'], ['docker-compose.local.yaml']],
    ids=['base', 'prod', 'local'],
)
def test_only_nginx_publishes_ports(tmp_path, overlays):
    cfg = config(tmp_path, ['docker-compose.yaml', *overlays])
    assert set(published(cfg)) == {'nginx'}


def test_dev_publishes_on_loopback_only(tmp_path):
    cfg = config(tmp_path, ['docker-compose.yaml', 'docker-compose.dev.yaml'])
    ports = published(cfg)
    assert set(ports) == {'postgres', 'redis', 'web'}
    for name, entries in ports.items():
        for entry in entries:
            assert entry.get('host_ip') == '127.0.0.1', (name, entry)


@pytest.mark.parametrize(
    ('compose_file', 'service', 'variable'),
    [
        ('docker-compose.db.yaml', 'postgres', 'POSTGRES_BIND_ADDRESS'),
        ('docker-compose.minio.yaml', 'minio', 'MINIO_BIND_ADDRESS'),
    ],
)
def test_standalone_servers_need_an_explicit_bind_address(
    tmp_path, compose_file, service, variable
):
    missing = render(tmp_path, [compose_file], unset=[variable])
    assert missing.returncode != 0
    assert variable in missing.stderr

    cfg = config(tmp_path, [compose_file], {variable: '10.0.0.5'})
    for entry in cfg['services'][service]['ports']:
        assert entry['host_ip'] == '10.0.0.5', entry


def test_redis_requires_auth_and_clients_carry_the_password(tmp_path):
    services = config(tmp_path, ['docker-compose.yaml'])['services']
    password = BASE_ENV['REDIS_PASSWORD']

    redis = services['redis']
    assert redis['command'] == ['redis-server', '--requirepass', password]
    assert redis['environment']['REDISCLI_AUTH'] == password

    # web.server.configuration builds (and URL-encodes) the broker URL and the
    # cache settings from these two, so Compose never embeds the password in a URL.
    for client in ('web', 'worker'):
        environment = services[client]['environment']
        assert environment['REDIS_HOST'] == 'redis', client
        assert environment['REDIS_PASSWORD'] == password, client
        assert 'BROKER_URL' not in environment, client


# MinIO no longer publishes server images, so its replacement waits on a
# human decision (WP-0b request R5).
UNPINNED_UNTIL_DECIDED = {'minio'}
OWN_IMAGE_PREFIXES = ('ghcr.io/zenysis/', 'harmony-dev-web:')


@pytest.mark.parametrize(
    'files',
    [
        ['docker-compose.yaml', 'docker-compose.prod.yaml'],
        ['docker-compose.yaml', 'docker-compose.dev.yaml'],
        ['docker-compose.db.yaml'],
        ['docker-compose.minio.yaml'],
    ],
)
def test_third_party_images_are_pinned_by_digest(tmp_path, files):
    services = config(tmp_path, files)['services']
    for name, service in services.items():
        image = service['image']
        if name in UNPINNED_UNTIL_DECIDED or image.startswith(OWN_IMAGE_PREFIXES):
            continue
        reference, _, digest = image.partition('@sha256:')
        assert len(digest) == 64, f'{name}: {image} is not pinned by digest'
        tag = reference.rpartition(':')[2]
        assert any(ch.isdigit() for ch in tag), f'{name}: {image} has no version tag'


REQUIRED_SECRETS = [
    (['docker-compose.yaml'], 'DEFAULT_SECRET_KEY'),
    (['docker-compose.yaml'], 'JWT_SECRET_KEY'),
    (['docker-compose.yaml'], 'REDIS_PASSWORD'),
    (['docker-compose.yaml'], 'HASURA_ADMIN_SECRET'),
    (['docker-compose.yaml', 'docker-compose.dev.yaml'], 'DEFAULT_SECRET_KEY'),
    (['docker-compose.pipeline.yaml'], 'DEFAULT_SECRET_KEY'),
    (['docker-compose.db.yaml'], 'POSTGRES_PASSWORD'),
    (['docker-compose.minio.yaml'], 'MINIO_ROOT_USER'),
    (['docker-compose.minio.yaml'], 'MINIO_ROOT_PASSWORD'),
]


@pytest.mark.parametrize(('files', 'variable'), REQUIRED_SECRETS)
@pytest.mark.parametrize('value', [None, ''], ids=['unset', 'empty'])
def test_refuses_to_render_without_secret(tmp_path, files, variable, value):
    if value is None:
        result = render(tmp_path, files, unset=[variable])
    else:
        result = render(tmp_path, files, {variable: value})
    assert result.returncode != 0
    assert f'required variable {variable} is missing a value' in result.stderr


@pytest.mark.parametrize(
    'files',
    [
        ['docker-compose.yaml'],
        ['docker-compose.yaml', 'docker-compose.prod.yaml'],
        ['docker-compose.yaml', 'docker-compose.dev.yaml'],
        ['docker-compose.pipeline.yaml'],
        ['docker-compose.db.yaml'],
        ['docker-compose.minio.yaml'],
    ],
)
def test_no_default_secret_in_rendered_config(tmp_path, files):
    result = render(tmp_path, files)
    assert result.returncode == 0, result.stderr
    assert 'changeme' not in result.stdout.lower()
