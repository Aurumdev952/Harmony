"""The web and worker containers never run as root (security finding F1, WP-3b).

Images before WP-3b ran as root, so existing hosts have root-owned data
directories. A root entrypoint that handed them over could be steered by the app
user: a symlink planted at `~/.mc` made the next restart chown its target. Now the
image and the production Compose services run as uid 1000, the MinIO client
config is mounted read-only, and a one-shot `data-owner` service hands the bind
mounts over as root before web and worker start, without following symlinks.

The tests that start containers are marked `stack` (CI's python-stack job).
"""

import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from tests.infra.test_compose import config

REPO = Path(__file__).resolve().parents[2]
APP_SERVICES = ['web', 'worker']
PROD = ['docker-compose.yaml', 'docker-compose.prod.yaml']

pytestmark = pytest.mark.skipif(
    shutil.which('docker') is None, reason='docker CLI not available'
)


def test_the_web_image_runs_as_uid_1000():
    users = re.findall(
        r'^USER\s+(\S+)', (REPO / 'docker/web/Dockerfile_web').read_text(), re.M
    )
    assert users[-1:] == ['1000:1000']


@pytest.mark.parametrize('name', APP_SERVICES)
def test_production_app_services_run_as_uid_1000(tmp_path, name):
    service = config(tmp_path, PROD)['services'][name]
    assert service.get('user') == '1000:1000'
    assert service['depends_on']['data-owner']['condition'] == (
        'service_completed_successfully'
    )


@pytest.mark.parametrize('name', APP_SERVICES)
def test_the_mc_config_is_mounted_read_only_in_the_app_home(tmp_path, name):
    mounts = [
        v
        for v in config(tmp_path, PROD)['services'][name].get('volumes', [])
        if '/.mc' in v['target']
    ]
    assert mounts, f'{name} mounts no MinIO client config'
    for mount in mounts:
        assert mount['target'].startswith('/home/zenysis/.mc'), mount
        assert mount.get('read_only') is True, mount


def test_only_the_one_shot_data_owner_runs_as_root(tmp_path):
    services = config(tmp_path, PROD)['services']
    owner = services['data-owner']
    assert owner['user'] == '0:0'
    assert owner['network_mode'] == 'none'
    assert owner['cap_drop'] == ['ALL']
    assert set(owner['cap_add']) <= {'CHOWN', 'DAC_READ_SEARCH'}
    assert 'no-new-privileges:true' in owner['security_opt']
    assert owner.get('restart', 'no') == 'no'
    assert 'ports' not in owner
    for name in APP_SERVICES:
        targets = {v['target'] for v in services[name].get('volumes', [])}
        writable = {'/data/output', '/zenysis/uploads'} & targets
        owned = {v['target'] for v in owner['volumes']}
        assert writable <= owned, f'{name} writes {writable - owned}, not handed over'


# Containers from here on.


def _docker(*args, check=True):
    return subprocess.run(
        ['docker', *args], capture_output=True, text=True, check=check
    ).stdout.strip()


@pytest.fixture(name='web_image', scope='module')
def fixture_web_image(tmp_path_factory):
    """docker/web/Dockerfile_web over stand-ins for the client and server images:
    the server stand-in is the server image's base and its app user, so the
    entrypoint, USER and scripts under test are the real ones."""
    work = tmp_path_factory.mktemp('web-image')
    server = (REPO / 'docker/web/Dockerfile_web-server').read_text()
    base = re.findall(r'^FROM\s+(\S+)', server, re.M)[-1]
    user = re.search(r'^RUN groupadd .*?zenysis$', server, re.M | re.S).group(0)
    namespace = f'harmony-test-{uuid.uuid4().hex[:12]}'
    images = [
        f'{namespace}/harmony-{name}:t' for name in ('web-server', 'web-client', 'web')
    ]
    (work / 'server.Dockerfile').write_text(f'FROM {base}\n{user}\n')
    (work / 'index.html').write_text('stand-in client\n')
    (work / 'client.Dockerfile').write_text('FROM scratch\nCOPY index.html /client/\n')
    try:
        _docker(
            'build',
            '-q',
            '-f',
            str(work / 'server.Dockerfile'),
            '-t',
            images[0],
            str(work),
        )
        _docker(
            'build',
            '-q',
            '-f',
            str(work / 'client.Dockerfile'),
            '-t',
            images[1],
            str(work),
        )
        _docker(
            'build', '-q', '-f', str(REPO / 'docker/web/Dockerfile_web'),
            '--build-arg', f'NAMESPACE={namespace}', '--build-arg', 'TAG=t',
            '-t', images[2], str(REPO),
        )  # fmt: skip
        yield images[2]
    finally:
        _docker('rmi', *images, check=False)


@pytest.mark.stack
@pytest.mark.parametrize('name', APP_SERVICES)
def test_a_symlink_at_mc_cannot_make_a_restart_chown_a_root_path(
    tmp_path, web_image, name
):
    service = config(tmp_path, PROD)['services'][name]
    mc = tmp_path / 'mc'
    mc.mkdir()
    (mc / 'config.json').write_text('{"version": "10", "aliases": {}}\n')
    args = ['run', '-d', '--network', 'none']
    if service.get('user'):
        args += ['--user', service['user']]
    for volume in service.get('volumes', []):
        if '/.mc' not in volume['target']:
            continue
        source = mc / 'config.json' if volume['target'].endswith('.json') else mc
        mode = ':ro' if volume.get('read_only') else ''
        args += ['-v', f'{source}:{volume["target"]}{mode}']
    container = _docker(*args, web_image, 'sleep', 'infinity')
    try:
        # The app user replaces ~/.mc with a symlink to a root-owned directory.
        _docker(
            'exec', '-u', '1000:1000', container, 'sh', '-c',
            'rm -rf /home/zenysis/.mc; ln -sfn /usr/local/bin /home/zenysis/.mc',
            check=False,
        )  # fmt: skip
        _docker('restart', '-t', '1', container)
        owner = _docker(
            'exec', '-u', '0', container, 'stat', '-c', '%u:%g', '/usr/local/bin'
        )
        assert owner == '0:0'
    finally:
        _docker('rm', '-f', container, check=False)


@pytest.mark.stack
def test_the_data_owner_hands_over_without_following_symlinks(tmp_path, web_image):
    service = config(tmp_path, PROD)['services']['data-owner']
    tag = uuid.uuid4().hex[:12]
    volumes = {
        v['target']: f'harmony-test-{tag}-{i}' for i, v in enumerate(service['volumes'])
    }
    mounts = [
        arg for target, name in volumes.items() for arg in ('-v', f'{name}:{target}')
    ]
    owner, after = f'harmony-test-{tag}-owner', f'{web_image}-{tag}'
    # A host written by root-run images, plus symlinks the app user planted and
    # a hardlink to a root-owned file outside the handed-over trees (hasura's log,
    # on the same filesystem).
    layout = (
        'set -e; mkdir -p /data/output/zenysis_static/build /data/output/logs '
        '/zenysis/uploads/2024; echo x > /data/output/zenysis.log; '
        'echo x > /data/output/zenysis_static/build/a.js; echo x > /data/output/logs/hasura.log; '
        'echo x > /zenysis/uploads/2024/r.csv; chown -R 0:0 /data/output /zenysis/uploads; '
        'ln /data/output/logs/hasura.log /data/output/zenysis_static/build/hardlinked.js; '
        'ln -s /usr/local/bin /data/output/planted.log; '
        'ln -s /usr/local/bin /data/output/zenysis_static/build/planted; '
        'ln -s /usr/local/bin /zenysis/uploads/planted'
    )
    try:
        _docker('run', '--rm', '--network', 'none', '--user', '0', *mounts,
                '--entrypoint', 'sh', web_image, '-c', layout)  # fmt: skip
        run = subprocess.run(
            [
                'docker', 'run', '--name', owner, '--network', 'none',
                '--user', service['user'], '--cap-drop', 'ALL',
                *[f'--cap-add={c}' for c in service['cap_add']],
                *[f'--security-opt={o}' for o in service['security_opt']],
                *mounts, '--entrypoint', service['entrypoint'][0], web_image,
                *(service.get('command') or []),
            ],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        assert run.returncode == 0, run.stdout + run.stderr
        _docker('commit', owner, after)
        owners = _docker(
            'run', '--rm', '--network', 'none', '--user', '0', *mounts,
            '--entrypoint', 'stat', after, '-c', '%n %u:%g', '/usr/local/bin',
            '/data/output', '/data/output/zenysis.log',
            '/data/output/zenysis_static/build/a.js', '/zenysis/uploads/2024/r.csv',
            '/data/output/logs/hasura.log',
        )  # fmt: skip
        assert owners.splitlines() == [
            '/usr/local/bin 0:0',
            '/data/output 1000:1000',
            '/data/output/zenysis.log 1000:1000',
            '/data/output/zenysis_static/build/a.js 1000:1000',
            '/zenysis/uploads/2024/r.csv 1000:1000',
            '/data/output/logs/hasura.log 0:0',
        ]
        assert 'hardlinked.js' in run.stderr, 'a skipped hardlink is reported'
    finally:
        _docker('rm', '-f', owner, check=False)
        _docker('rmi', after, check=False)
        _docker('volume', 'rm', *volumes.values(), check=False)
