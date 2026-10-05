"""Every Dockerfile under docker/ pins its frontend and base images by digest, and
every Python image copies the first-party code that loading a deployment imports."""

import ast
import re
import tomllib
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


# Images whose processes (web server, worker, pipeline steps) import `config`.
PYTHON_IMAGES = ['docker/web/Dockerfile_web-server', 'docker/pipeline/Dockerfile']
COPY = re.compile(r'COPY\s+(.+)$', re.IGNORECASE)


def copied_top_level_paths(dockerfile):
    '''Top-level repo paths that a Dockerfile copies from the build context.'''
    copied = set()
    for line in dockerfile.read_text().splitlines():
        match = COPY.match(line.strip())
        if not match:
            continue
        words = match.group(1).split()
        if any(word.startswith('--from') for word in words):
            continue
        sources = [word for word in words if not word.startswith('--')][:-1]
        copied.update(source.lstrip('./').split('/')[0] for source in sources)
    return copied


def module_file(name):
    path = REPO.joinpath(*name.split('.'))
    for candidate in (path / '__init__.py', path.with_suffix('.py')):
        if candidate.is_file():
            return candidate
    return None


def imported_names(path):
    '''Absolute module names imported anywhere outside function bodies.'''
    names = []
    pending = list(ast.parse(path.read_text()).body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
            names.extend(f'{node.module}.{alias.name}' for alias in node.names)
        pending.extend(ast.iter_child_nodes(node))
    return names


def first_party_closure(start):
    '''Repo files reachable from `start` through module-level imports, including
    each imported module's parent packages.'''
    seen = set()
    pending = list(start)
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        for name in imported_names(path):
            parts = name.split('.')
            for depth in range(1, len(parts) + 1):
                target = module_file('.'.join(parts[:depth]))
                if target is not None:
                    pending.append(target)
    return seen


def deployment_loading_packages():
    '''Top-level packages that `import config` plus loading any deployment
    (every module under config/) reaches.'''
    start = sorted((REPO / 'config').rglob('*.py'))
    return {path.relative_to(REPO).parts[0] for path in first_party_closure(start)}


def test_deployment_loading_reaches_harmony_core():
    assert 'harmony' in deployment_loading_packages()


@pytest.mark.parametrize('dockerfile', PYTHON_IMAGES)
def test_python_images_copy_what_deployment_loading_imports(dockerfile):
    missing = deployment_loading_packages() - copied_top_level_paths(REPO / dockerfile)
    assert missing == set(), f'{dockerfile} does not copy {sorted(missing)}'


def stage_names(dockerfile):
    return {stage for _, stage in FROM.findall(dockerfile) if stage}


def test_pipeline_pypy_wheel_stages_live_exactly_as_long_as_the_pypy_venv():
    dockerfile = (REPO / 'docker/pipeline/Dockerfile').read_text()
    creates_venv = 'pypy3 -m venv venv_pypy3' in dockerfile
    wheel_stages = {'rust', 'pypy-wheels'} & stage_names(dockerfile)
    if not creates_venv:
        assert wheel_stages == set(), f'dead PyPy wheel stages: {sorted(wheel_stages)}'
        return
    assert wheel_stages == {'rust', 'pypy-wheels'}
    lock = tomllib.loads((REPO / 'uv.lock').read_text())
    locked = {p['name']: p['version'] for p in lock['package']}['pydantic-core']
    built = re.search(r'ARG PYDANTIC_CORE_VERSION=(\S+)', dockerfile).group(1)
    assert built == locked
