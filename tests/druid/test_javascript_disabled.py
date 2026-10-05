'''SEC-8: Druid runs with JavaScript disabled, and nothing the builder posts needs it.

A Druid with JavaScript disabled refuses a JavaScript extraction (WP-8a evidence);
these pin the setting in both druid_setup modes and keep JavaScript out of the
granularity extractions, its only former use in the query path.
'''

from pathlib import Path
from typing import Any, Iterator

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTING = 'druid_javascript_enabled'


def _assignments(path: Path) -> list:
    return [
        line.split('=', 1)[1].strip()
        for line in path.read_text(encoding='utf-8').splitlines()
        if line.split('=', 1)[0].strip() == SETTING
    ]


@pytest.mark.parametrize('mode', ['single', 'cluster'])
def test_druid_setup_disables_javascript(mode):
    assert _assignments(REPO_ROOT / f'druid_setup/{mode}/environment/common.env') == [
        'false'
    ]


def test_no_compose_file_overrides_the_setting():
    for path in sorted((REPO_ROOT / 'druid_setup').rglob('*')):
        if path.is_file() and path.suffix in ('.yml', '.yaml', '.env', '.properties'):
            if path.name == 'common.env':
                continue
            assert SETTING not in path.read_text(encoding='utf-8'), path
            assert 'druid.javascript.enabled' not in path.read_text(encoding='utf-8')


def _types(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        if isinstance(node.get('type'), str):
            yield node['type']
        for value in node.values():
            yield from _types(value)
    elif isinstance(node, list):
        for item in node:
            yield from _types(item)


def test_no_granularity_extraction_is_javascript():
    from data.query.models.granularity.granularity_extraction import (
        GranularityExtraction,
    )

    for name, extraction in GranularityExtraction.EXTRACTION_MAP.items():
        assert 'javascript' not in set(_types(extraction.build())), name
