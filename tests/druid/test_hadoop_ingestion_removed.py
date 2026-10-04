"""The Hadoop ingestion path is gone; native indexing still imports."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_hadoop_ingestion_modules_are_gone():
    sys.path.insert(0, str(REPO_ROOT))
    try:
        for name in (
            'db.druid.indexing.legacy_task_builder',
            'db.druid.indexing.scripts.run_indexing',
        ):
            assert importlib.util.find_spec(name) is None, name
    finally:
        sys.path.remove(str(REPO_ROOT))
    assert not (REPO_ROOT / 'db/druid/indexing/resources').exists()


def test_native_indexing_imports_without_druid():
    # A subprocess keeps the dummy settings out of this test session's modules.
    env = {
        **os.environ,
        'PYTHONPATH': str(REPO_ROOT),
        'ZEN_HOME': str(REPO_ROOT),
        'R77_SRC_ROOT': str(REPO_ROOT),
        'ZEN_ENV': os.environ.get('ZEN_ENV', 'harmony_demo'),
        'DRUID_HOST': 'http://druid.invalid',
        'DEFAULT_SECRET_KEY': 'test-only-not-a-secret',
    }
    result = subprocess.run(
        [sys.executable, '-c', 'import db.druid.indexing.scripts.run_native_indexing'],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
