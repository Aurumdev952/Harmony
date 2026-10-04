"""Checks on the guards druid_setup/Makefile runs before any Compose call.

Run with: uv run --no-project --with pytest pytest tests/druid_setup
"""

import shutil
import subprocess
from pathlib import Path

import pytest

DRUID_SETUP = Path(__file__).resolve().parents[2] / 'druid_setup'

pytestmark = pytest.mark.skipif(
    shutil.which('make') is None, reason='make not available'
)

UP_TARGETS = ['single_server_up', 'cluster_server_up']
GOOD_PASSWORD = '5f2a91c0e4b7d3a8'
PINNED_POSTGRES = (
    'postgres:16.15-bookworm@sha256:'
    'efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67'
)


GOOD_BIND_ADDRESS = '10.0.0.20'
CLUSTER_HOST_VARIABLES = ['DRUID_MASTER_HOST', 'DRUID_DATA_HOST', 'DRUID_QUERY_HOST']
WILDCARD_ADDRESSES = ['', '0.0.0.0', '::', '[::]', ' 0.0.0.0 ']


def run_make(tmp_path, target, shell=None, make_vars=None, **values):
    """Runs a Makefile target with a stub `docker` that only logs its calls.

    `values` go to the operator's druid_setup/.env (None leaves a key out);
    `shell` is the caller's environment, which Compose prefers over
    cluster/cluster.env; `make_vars` override Makefile variables.
    """
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / 'docker-calls'
    docker = bin_dir / 'docker'
    docker.write_text(f'#!/bin/sh\necho "$@" >> {calls}\n')
    docker.chmod(0o755)
    values = {'DRUID_BIND_ADDRESS': GOOD_BIND_ADDRESS, **values}
    env_file = tmp_path / 'druid.env'
    env_file.write_text(
        ''.join(f'{k}={v}\n' for k, v in values.items() if v is not None)
    )
    result = subprocess.run(
        [
            'make',
            '--no-print-directory',
            f'ENV_FILE={env_file}',
            *(f'{k}={v}' for k, v in (make_vars or {}).items()),
            target,
        ],
        capture_output=True,
        text=True,
        cwd=DRUID_SETUP,
        env={'PATH': f'{bin_dir}:/usr/bin:/bin', **(shell or {})},
        check=False,
    )
    return result, calls.read_text() if calls.exists() else ''


@pytest.mark.parametrize('target', UP_TARGETS)
def test_starts_with_a_real_password(tmp_path, target):
    result, calls = run_make(tmp_path, target, DRUID_POSTGRES_PASSWORD=GOOD_PASSWORD)
    assert result.returncode == 0, result.stderr
    assert 'compose' in calls


@pytest.mark.parametrize('target', UP_TARGETS)
@pytest.mark.parametrize(
    'password', ['', 'FoolishPassword', 'foolishpassword', 'FOOLISHPASSWORD ']
)
def test_refuses_empty_or_default_password(tmp_path, target, password):
    result, calls = run_make(tmp_path, target, DRUID_POSTGRES_PASSWORD=password)
    assert result.returncode != 0
    assert 'DRUID_POSTGRES_PASSWORD' in result.stderr
    assert calls == ''


@pytest.mark.parametrize('target', UP_TARGETS)
def test_accepts_a_pinned_postgres_override(tmp_path, target):
    result, calls = run_make(
        tmp_path,
        target,
        DRUID_POSTGRES_PASSWORD=GOOD_PASSWORD,
        DRUID_POSTGRES_IMAGE=PINNED_POSTGRES,
    )
    assert result.returncode == 0, result.stderr
    assert 'compose' in calls


@pytest.mark.parametrize('target', UP_TARGETS)
@pytest.mark.parametrize(
    'image',
    [
        'postgres:16',
        'postgres:latest',
        'postgres@sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67',
        'postgres:16.15-bookworm@sha256:efedf359',
        f'{PINNED_POSTGRES} ; true',
    ],
)
def test_refuses_an_unpinned_postgres_override(tmp_path, target, image):
    result, calls = run_make(
        tmp_path,
        target,
        DRUID_POSTGRES_PASSWORD=GOOD_PASSWORD,
        DRUID_POSTGRES_IMAGE=image,
    )
    assert result.returncode != 0
    assert 'DRUID_POSTGRES_IMAGE' in result.stderr
    assert calls == ''


@pytest.mark.parametrize('address', [None, *WILDCARD_ADDRESSES])
def test_single_refuses_a_missing_or_wildcard_bind_address(tmp_path, address):
    result, calls = run_make(
        tmp_path,
        'single_server_up',
        DRUID_POSTGRES_PASSWORD=GOOD_PASSWORD,
        DRUID_BIND_ADDRESS=address,
    )
    assert result.returncode != 0
    assert 'DRUID_BIND_ADDRESS' in result.stderr
    assert calls == ''


def test_cluster_accepts_private_host_addresses(tmp_path):
    shell = {
        variable: f'10.0.0.{i}' for i, variable in enumerate(CLUSTER_HOST_VARIABLES)
    }
    result, calls = run_make(
        tmp_path, 'cluster_server_up', shell, DRUID_POSTGRES_PASSWORD=GOOD_PASSWORD
    )
    assert result.returncode == 0, result.stderr
    assert 'compose' in calls


@pytest.mark.parametrize('variable', CLUSTER_HOST_VARIABLES)
@pytest.mark.parametrize('address', WILDCARD_ADDRESSES)
def test_cluster_refuses_a_wildcard_host_address(tmp_path, variable, address):
    result, calls = run_make(
        tmp_path,
        'cluster_server_up',
        {variable: address},
        DRUID_POSTGRES_PASSWORD=GOOD_PASSWORD,
    )
    assert result.returncode != 0
    assert variable in result.stderr
    assert calls == ''


@pytest.mark.parametrize('variable', CLUSTER_HOST_VARIABLES)
def test_cluster_refuses_a_wildcard_in_cluster_env(tmp_path, variable):
    # Without a value in the shell, Compose takes the cluster env file's.
    cluster_env = tmp_path / 'cluster.env'
    cluster_env.write_text(
        (DRUID_SETUP / 'cluster' / 'cluster.env').read_text() + f'{variable}=0.0.0.0\n'
    )
    result, calls = run_make(
        tmp_path,
        'cluster_server_up',
        make_vars={'CLUSTER_ENV': cluster_env},
        DRUID_POSTGRES_PASSWORD=GOOD_PASSWORD,
    )
    assert result.returncode != 0
    assert variable in result.stderr
    assert calls == ''
