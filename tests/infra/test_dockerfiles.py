"""Every Dockerfile under docker/ pins its frontend and base images by digest."""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCKERFILES = sorted((REPO / 'docker').rglob('Dockerfile*'))
DIGEST = re.compile(r'@sha256:[0-9a-f]{64}$')
FROM = re.compile(
    r'FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?', re.IGNORECASE
)


@pytest.mark.parametrize('path', DOCKERFILES, ids=lambda p: str(p.relative_to(REPO)))
def test_frontend_and_base_images_are_pinned(path):
    stages = set()
    for line in path.read_text().splitlines():
        syntax = re.match(r'#\s*syntax=(\S+)', line)
        if syntax:
            assert DIGEST.search(syntax.group(1)), f'floating frontend: {line}'
        source = FROM.match(line)
        if not source:
            continue
        image, stage = source.groups()
        # Stages and our own images (built from ARGs) are not third-party pulls.
        if image not in stages and '$' not in image:
            assert DIGEST.search(image), f'unpinned base image: {line}'
        if stage:
            stages.add(stage)
