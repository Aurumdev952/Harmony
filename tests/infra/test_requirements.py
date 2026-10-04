"""Checks that pinned Python requirements work together.

Run with: uv run --no-project --with pytest pytest tests/infra
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def pinned(name):
    for line in (REPO / 'requirements.txt').read_text().splitlines():
        match = re.match(rf'{name}==([^\s;]+)', line, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


@pytest.mark.skipif(shutil.which('uv') is None, reason='uv not available')
def test_passlib_can_hash_with_the_installed_bcrypt():
    # scripts/create_user.py and Flask-User hash through passlib 1.7.4, which
    # raises on bcrypt >= 5.0 (4.1 to 4.3 only log a version warning). Without
    # a pin, pip resolves the newest bcrypt.
    bcrypt = pinned('bcrypt')
    assert bcrypt, 'bcrypt is not pinned in requirements.txt'
    script = (
        'from passlib.context import CryptContext\n'
        "c = CryptContext(schemes=['bcrypt'])\n"
        "assert c.verify('password', c.hash('password'))"
    )
    uv_run = ['uv', 'run', '--no-project', '--python', '3.8']
    packages = ['--with', 'passlib==1.7.4', '--with', f'bcrypt=={bcrypt}']
    result = subprocess.run(
        [*uv_run, *packages, 'python', '-W', 'ignore', '-c', script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
