"""Native indexing still imports once the Hadoop ingestion path is deleted."""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


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
