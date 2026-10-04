"""Checks that every Druid extension download is pinned and checksummed.

Run with: uv run --no-project --with pytest pytest tests/druid_setup
"""

import re
from pathlib import Path

DRUID_SETUP = Path(__file__).resolve().parents[2] / 'druid_setup'
SCRIPT = DRUID_SETUP / 'extensions' / 'load_extensions.sh'

URL = re.compile(r'https?://[^\s"\']+')
# "<sha256>  <path under the extensions directory>  <url>"
ENTRY = re.compile(r'^\s*"([0-9a-f]{64})\s+(\S+\.jar)\s+(https://\S+)"\s*$')
GITHUB_RAW = re.compile(r'^https://github\.com/[^/]+/[^/]+/raw/([^/]+)/')


def entries():
    return [m.groups() for m in map(ENTRY.match, SCRIPT.read_text().splitlines()) if m]


def test_every_download_url_has_a_checksum():
    urls = URL.findall(SCRIPT.read_text())
    covered = {url for _, _, url in entries()}
    assert urls, 'no download URLs found'
    assert [url for url in urls if url not in covered] == []


def test_urls_do_not_contain_variables():
    assert [url for _, _, url in entries() if '$' in url] == []


def test_github_downloads_are_pinned_to_a_commit():
    for _, _, url in entries():
        match = GITHUB_RAW.match(url)
        if match:
            assert re.fullmatch(r'[0-9a-f]{40}', match.group(1)), url


def test_script_verifies_checksums_before_installing():
    text = SCRIPT.read_text()
    assert 'sha256sum -c' in text
    # A failed download must leave the installed extensions in place.
    assert text.index('sha256sum -c') < text.index('rm -rf "${destination')


def test_extension_version_matches_druid_image():
    druid_versions = {
        match
        for path in DRUID_SETUP.rglob('docker-compose*.yml')
        for match in re.findall(r'apache/druid:([\w.-]+)@', path.read_text())
    }
    assert len(druid_versions) == 1, druid_versions
    (druid_version,) = druid_versions
    for _, path, _ in entries():
        assert path.endswith(f'-{druid_version}.jar'), path
