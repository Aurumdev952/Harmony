import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VALID_KEY = 'k' * 64


def _import_worker(**secrets: str) -> subprocess.CompletedProcess:
    # A fresh interpreter, because `celery -A web.background_worker.celery` imports
    # the entry point once, before it starts the pool.
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ('DEFAULT_SECRET_KEY', 'JWT_SECRET_KEY', 'SECRET_KEY')
    }
    env.update(
        DRUID_HOST='http://druid.invalid',
        ZEN_ENV='harmony_demo',
        PYTHONPATH=str(REPO),
        # Never connected to: the engine is created lazily.
        SQLALCHEMY_DATABASE_URI='postgresql://u:p@db.invalid/harmony',
        **secrets,
    )
    return subprocess.run(
        [sys.executable, '-c', 'import web.background_worker'],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    'secrets, variable',
    [
        (
            {'DEFAULT_SECRET_KEY': 'changeme', 'JWT_SECRET_KEY': VALID_KEY},
            'DEFAULT_SECRET_KEY',
        ),
        (
            {'DEFAULT_SECRET_KEY': VALID_KEY, 'JWT_SECRET_KEY': 'changeme'},
            'JWT_SECRET_KEY',
        ),
        ({'DEFAULT_SECRET_KEY': VALID_KEY}, 'JWT_SECRET_KEY'),
        (
            {'DEFAULT_SECRET_KEY': VALID_KEY, 'JWT_SECRET_KEY': 'short'},
            'JWT_SECRET_KEY',
        ),
    ],
    ids=['default-secret-changeme', 'jwt-changeme', 'jwt-unset', 'jwt-short'],
)
def test_worker_refuses_to_load_with_an_unusable_key(secrets, variable):
    result = _import_worker(**secrets)

    assert result.returncode != 0
    last_line = result.stderr.strip().splitlines()[-1]
    assert last_line.startswith('RuntimeError: ')
    assert variable in last_line


def test_worker_loads_with_usable_keys():
    result = _import_worker(DEFAULT_SECRET_KEY=VALID_KEY, JWT_SECRET_KEY='j' * 64)

    assert result.returncode == 0, result.stderr
