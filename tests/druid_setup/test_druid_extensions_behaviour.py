"""Runs load_extensions.sh with a stub wget to prove a bad download stops it.

The text checks in test_druid_extensions.py cannot tell `sha256sum -c -`
from `sha256sum -c - || true`; this test can.
"""

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / 'druid_setup/extensions/load_extensions.sh'
)
DESTINATION_LINE = 'destination=/druid/extensions'
STUB_BYTES = b'not the jar you pinned\n'

pytestmark = pytest.mark.skipif(
    shutil.which('bash') is None or shutil.which('sha256sum') is None,
    reason='needs bash and sha256sum',
)

STUB_WGET = """#!/bin/bash
# Writes fixed bytes to the -O target, whatever the URL.
while [ $# -gt 0 ]; do
  case "$1" in
    -O) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf 'not the jar you pinned\\n' > "$out"
"""


def run_loader(tmp_path, script_text):
    text = SCRIPT.read_text() if script_text is None else script_text
    assert text.count(DESTINATION_LINE) == 1
    destination = tmp_path / 'extensions'
    existing = destination / 'druid-arbitrary-granularity' / 'existing.jar'
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b'jar already in the volume')
    script = tmp_path / 'load_extensions.sh'
    script.write_text(text.replace(DESTINATION_LINE, f'destination={destination}'))
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    wget = bin_dir / 'wget'
    wget.write_text(STUB_WGET)
    wget.chmod(0o755)
    result = subprocess.run(
        ['bash', str(script)],
        env={'PATH': f'{bin_dir}:/usr/bin:/bin', 'TMPDIR': str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result, destination, existing


def test_checksum_mismatch_stops_before_touching_the_volume(tmp_path):
    result, _, existing = run_loader(tmp_path, None)
    assert result.returncode != 0, result.stdout + result.stderr
    assert 'FAILED' in result.stdout + result.stderr
    assert existing.read_bytes() == b'jar already in the volume'


def test_matching_checksums_replace_the_volume(tmp_path):
    # Positive control: with the table rewritten to the stub's checksum the
    # same harness succeeds, so the failure above is the checksum, not the stub.
    stub_sha = hashlib.sha256(STUB_BYTES).hexdigest()
    text = re.sub(r'"[0-9a-f]{64}  ', f'"{stub_sha}  ', SCRIPT.read_text())
    result, destination, existing = run_loader(tmp_path, text)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not existing.exists()
    jars = sorted(p.relative_to(destination) for p in destination.rglob('*.jar'))
    assert len(jars) == 5
    assert all(p.read_bytes() == STUB_BYTES for p in destination.rglob('*.jar'))
