"""Checks on the export renderer's image and Compose services (WP-1h).

Run with: uv run --project ci/tools313 --locked pytest tests/infra
"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / 'docker/renderer/Dockerfile'
SECCOMP = REPO / 'docker/renderer/seccomp_profile.json'
REQUIREMENTS = REPO / 'harmony/worker/renderer/requirements.txt'

# utils/docker/seccomp_profile.json at Playwright v1.63.0, byte for byte.
PLAYWRIGHT_SECCOMP_SHA256 = (
    'cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849'
)

# Dummy values only. An explicit env file stops Compose from reading the
# repository's real `.env`.
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

needs_docker = pytest.mark.skipif(
    shutil.which('docker') is None, reason='docker CLI not available'
)


def compose_config(tmp_path, files, env=None):
    values = {**DUMMY_ENV, **(env or {})}
    env_file = tmp_path / 'renderer-test.env'
    env_file.write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
    args = ['docker', 'compose', '--env-file', str(env_file)]
    for name in files:
        args += ['-f', str(REPO / name)]
    result = subprocess.run(
        [*args, 'config', '--format', 'json'],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={'PATH': '/usr/bin:/bin:/usr/local/bin', 'HOME': str(tmp_path)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(params=OVERLAYS, name='cfg')
def fixture_cfg(request, tmp_path):
    return compose_config(tmp_path, ['docker-compose.yaml', *OVERLAYS[request.param]])


def on_network(cfg, network):
    return {
        name
        for name, service in cfg['services'].items()
        if network in (service.get('networks') or {})
    }


def routes_out(cfg, service):
    return {
        network
        for network in cfg['services'][service].get('networks') or {}
        if not cfg['networks'][network].get('internal')
    }


@needs_docker
def test_renderer_shares_an_internal_network_only_with_web_and_its_proxy(cfg):
    assert cfg['networks']['render']['internal'] is True
    assert on_network(cfg, 'render') == {'web', 'renderer', 'render-egress'}
    assert set(cfg['services']['renderer']['networks']) == {'render'}
    assert set(cfg['services']['web']['networks']) == {'default', 'render'}


@needs_docker
def test_only_the_egress_proxy_relays_from_the_render_network_to_a_route_out(cfg):
    # web is the app itself; render-egress is the one service there to relay.
    with_a_route_out = {s for s in on_network(cfg, 'render') if routes_out(cfg, s)}
    assert with_a_route_out == {'web', 'render-egress'}
    # Its route out is a network of its own, not the default one that redis,
    # hasura and web share.
    assert set(cfg['services']['render-egress']['networks']) == {
        'render',
        'render-egress',
    }
    assert routes_out(cfg, 'render-egress') == {'render-egress'}
    assert on_network(cfg, 'render-egress') == {'render-egress'}


@needs_docker
@pytest.mark.parametrize('service', ['renderer', 'render-egress'])
def test_renderer_services_publish_no_port(cfg, service):
    assert not cfg['services'][service].get('ports')


@needs_docker
def test_egress_proxy_runs_hardened_from_the_renderer_image(cfg):
    proxy = cfg['services']['render-egress']
    assert proxy['image'] == cfg['services']['renderer']['image']
    assert proxy['entrypoint'] == [
        'python',
        '-m',
        'harmony.worker.renderer.egress_proxy',
    ]
    assert proxy['read_only'] is True
    assert proxy['cap_drop'] == ['ALL']
    assert not proxy.get('cap_add')
    assert not proxy.get('privileged')
    # Python as PID 1 ignores SIGTERM, so without an init every stop waits 10 s.
    assert proxy['init'] is True
    assert 'no-new-privileges:true' in proxy['security_opt']
    assert int(proxy['mem_limit']) == 128 * 1024**2
    assert proxy['pids_limit'] == 128
    # Not the image's HEALTHCHECK, which probes the renderer's /healthz on 8080.
    port = proxy['environment']['EGRESS_PROXY_PORT']
    assert f"('127.0.0.1', {port})" in ' '.join(proxy['healthcheck']['test'])


@needs_docker
def test_renderer_reaches_the_map_origins_through_the_proxy(cfg):
    renderer = cfg['services']['renderer']
    proxy = cfg['services']['render-egress']['environment']
    assert renderer['environment']['RENDERER_EGRESS_PROXY'] == (
        f"http://render-egress:{proxy['EGRESS_PROXY_PORT']}"
    )
    assert renderer['environment']['RENDERER_MAP_ORIGINS'] == 'https://api.mapbox.com'
    assert proxy['EGRESS_ALLOWED_ORIGINS'] == 'https://api.mapbox.com'
    # Only map exports need the proxy, so its health never holds the others up.
    assert renderer['depends_on']['render-egress']['condition'] == 'service_started'


@needs_docker
def test_one_setting_names_the_map_origins_for_renderer_and_proxy(tmp_path):
    origins = 'https://api.mapbox.com,https://tiles.example.org'
    services = compose_config(
        tmp_path, ['docker-compose.yaml'], {'RENDERER_MAP_ORIGINS': origins}
    )['services']
    assert services['renderer']['environment']['RENDERER_MAP_ORIGINS'] == origins
    assert services['render-egress']['environment']['EGRESS_ALLOWED_ORIGINS'] == origins


@needs_docker
def test_prod_restarts_the_egress_proxy_like_the_renderer(tmp_path):
    services = compose_config(
        tmp_path, ['docker-compose.yaml', 'docker-compose.prod.yaml']
    )['services']
    assert services['renderer']['restart'] == 'always'
    assert services['render-egress']['restart'] == 'always'


@needs_docker
def test_web_and_renderer_agree_on_the_origin(cfg):
    web = cfg['services']['web']['environment']
    renderer = cfg['services']['renderer']['environment']
    assert web['RENDERER_URL'] == 'http://renderer:8080'
    assert web['RENDER_WEB_ORIGIN'] == 'http://web:5000'
    assert renderer['RENDERER_ALLOWED_ORIGIN'] == web['RENDER_WEB_ORIGIN']


@needs_docker
def test_renderer_runs_hardened(cfg):
    renderer = cfg['services']['renderer']
    assert renderer['read_only'] is True
    assert set(renderer['tmpfs']) == {'/tmp', '/home/pwuser'}
    assert int(renderer['shm_size']) == 1024**3
    assert renderer['cap_drop'] == ['ALL']
    # The one capability Chromium's namespace sandbox needs (it chroots).
    assert renderer['cap_add'] == ['SYS_CHROOT']
    assert not renderer.get('privileged')
    # Chromium's helper processes are reparented to PID 1 when a browser closes;
    # without an init they stay zombies and count against pids_limit.
    assert renderer['init'] is True
    assert int(renderer['mem_limit']) == 2 * 1024**3
    assert renderer['pids_limit'] == 512
    options = renderer['security_opt']
    assert 'no-new-privileges:true' in options
    seccomp = [o.partition('=')[2] for o in options if o.startswith('seccomp=')]
    assert len(seccomp) == 1
    assert (REPO / seccomp[0]).resolve() == SECCOMP


@needs_docker
def test_urlbox_settings_are_gone(cfg):
    for name, service in cfg['services'].items():
        environment = service.get('environment') or {}
        assert 'URLBOX_API_KEY' not in environment, name
        assert 'RENDERBOT_EMAIL' not in environment, name


def test_seccomp_profile_is_playwrights():
    assert hashlib.sha256(SECCOMP.read_bytes()).hexdigest() == PLAYWRIGHT_SECCOMP_SHA256
    assert json.loads(SECCOMP.read_text())['defaultAction'] == 'SCMP_ACT_ERRNO'


def dockerfile_instructions():
    text = DOCKERFILE.read_text().replace('\\\n', ' ')
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            keyword, _, rest = line.partition(' ')
            yield keyword.upper(), rest.strip()


def test_base_image_is_pinned_and_matches_the_playwright_package():
    bases = [rest for keyword, rest in dockerfile_instructions() if keyword == 'FROM']
    assert len(bases) == 1
    match = re.fullmatch(
        r'mcr\.microsoft\.com/playwright/python:v(\S+)-noble@sha256:[0-9a-f]{64}',
        bases[0],
    )
    assert match, bases[0]
    pinned = re.search(r'^playwright==(\S+)', REQUIREMENTS.read_text(), re.MULTILINE)
    assert pinned and pinned.group(1) == match.group(1)


def test_dependencies_install_by_hash_only():
    installs = [
        rest
        for keyword, rest in dockerfile_instructions()
        if keyword == 'RUN' and 'pip install' in rest
    ]
    assert len(installs) == 1
    assert '--require-hashes' in installs[0]
    assert '--no-deps' in installs[0]


def test_image_runs_the_renderer_as_pwuser():
    instructions = list(dockerfile_instructions())
    users = [rest for keyword, rest in instructions if keyword == 'USER']
    assert users and users[-1] == 'pwuser'
    entrypoints = [rest for keyword, rest in instructions if keyword == 'ENTRYPOINT']
    assert json.loads(entrypoints[-1]) == ['python', '-m', 'harmony.worker.renderer']
    checks = [rest for keyword, rest in instructions if keyword == 'HEALTHCHECK']
    assert len(checks) == 1 and '/healthz' in checks[0]


@needs_docker
def test_build_overlay_builds_the_renderer(tmp_path):
    cfg = compose_config(tmp_path, ['docker-compose.build.yaml'])
    build = cfg['services']['renderer']['build']
    assert (Path(build['context']) / build['dockerfile']).resolve() == DOCKERFILE
