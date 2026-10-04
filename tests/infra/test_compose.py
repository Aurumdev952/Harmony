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
    'POSTGRES_DB_URI': 'postgresql://u:p@db.invalid:5432/harmony',
    'MC_CONFIG_PATH': '/tmp/mc',
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


def test_pipeline_passes_postgres_db_uri(tmp_path):
    cfg = config(tmp_path, ['docker-compose.pipeline.yaml'])
    environment = cfg['services']['etl-pipeline']['environment']
    assert environment.get('POSTGRES_DB_URI') == BASE_ENV['POSTGRES_DB_URI']
    assert 'POSTGRES_DB_URI:' not in environment
