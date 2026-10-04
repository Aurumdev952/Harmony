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


def run_make(tmp_path, target, **values):
    """Runs a Makefile target with a stub `docker` that only logs its calls."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / 'docker-calls'
    docker = bin_dir / 'docker'
    docker.write_text(f'#!/bin/sh\necho "$@" >> {calls}\n')
    docker.chmod(0o755)
    env_file = tmp_path / 'druid.env'
    env_file.write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
    result = subprocess.run(
        ['make', '--no-print-directory', f'ENV_FILE={env_file}', target],
        capture_output=True,
        text=True,
        cwd=DRUID_SETUP,
        env={'PATH': f'{bin_dir}:/usr/bin:/bin'},
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
