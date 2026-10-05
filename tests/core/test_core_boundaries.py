'''BE-1: the import-linter contract in pyproject.toml keeps web frameworks out of
`harmony.core`. CI runs every tests/ suite, so this enforces it.'''

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LINT_IMPORTS = Path(sys.executable).with_name('lint-imports')
ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _lint_imports(root: Path) -> tuple[int, str]:
    # lint-imports puts its working directory first on sys.path, so `root`
    # decides which harmony.core it analyses; the legacy packages come from REPO.
    proc = subprocess.run(
        [str(LINT_IMPORTS), '--config', str(REPO / 'pyproject.toml'), '--no-cache'],
        cwd=root,
        env={**os.environ, 'PYTHONPATH': str(REPO)},
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, ANSI.sub('', proc.stdout + proc.stderr)


def test_core_imports_no_web_framework():
    returncode, output = _lint_imports(REPO)

    assert returncode == 0, output
    assert 'BE-1: harmony.core imports no web framework KEPT' in output


def _namespace_directories(root: Path) -> list[str]:
    '''Directories under `root` that hold Python files but no __init__.py.'''
    return sorted(
        str(directory.relative_to(root.parent))
        for directory in [root, *root.rglob('*')]
        if directory.is_dir()
        and directory.name != '__pycache__'
        and any(directory.glob('*.py'))
        and not (directory / '__init__.py').exists()
    )


def test_every_harmony_directory_is_a_regular_package():
    # grimp does not descend into a namespace directory, so its modules would be
    # invisible to the BE-1 contract.
    assert _namespace_directories(REPO / 'harmony') == []


def test_namespace_check_finds_a_directory_without_init(tmp_path):
    (tmp_path / 'harmony' / 'worker' / 'renderer').mkdir(parents=True)
    (tmp_path / 'harmony' / '__init__.py').write_text('')
    (tmp_path / 'harmony' / 'worker' / 'tasks.py').write_text('')
    (tmp_path / 'harmony' / 'worker' / 'renderer' / '__init__.py').write_text('')

    assert _namespace_directories(tmp_path / 'harmony') == ['harmony/worker']


def _core_with(tmp_path: Path, source: str) -> Path:
    '''A copy of the whole harmony tree whose core gains `leak.py`.'''
    shutil.copytree(
        REPO / 'harmony',
        tmp_path / 'harmony',
        ignore=shutil.ignore_patterns('__pycache__'),
    )
    (tmp_path / 'harmony' / 'core' / 'leak.py').write_text(f'{source}\n')
    return tmp_path


@pytest.mark.parametrize(
    'leak',
    [
        'import flask',
        'from flask import current_app',
        'from fastapi import FastAPI',
        'import starlette.requests',
    ],
)
def test_contract_breaks_on_a_direct_import(tmp_path, leak):
    returncode, output = _lint_imports(_core_with(tmp_path, leak))

    assert returncode != 0, output
    assert 'BE-1: harmony.core imports no web framework BROKEN' in output
    framework = leak.split()[1].split('.')[0]
    assert f'harmony.core.leak -> {framework} ' in output


def test_contract_breaks_on_an_import_through_legacy_code(tmp_path):
    # web.server.app_base imports flask; core must not reach it through any path.
    returncode, output = _lint_imports(
        _core_with(tmp_path, 'from web.server import app_base')
    )

    assert returncode != 0, output
    assert 'harmony.core.leak -> web.server.app_base' in output


def test_contract_breaks_on_an_import_through_a_sibling_harmony_package(tmp_path):
    # harmony.api (phase 5) imports fastapi; core must not reach it either.
    root = _core_with(tmp_path, 'from harmony.api import router')
    api = root / 'harmony' / 'api'
    api.mkdir()
    (api / '__init__.py').write_text('')
    (api / 'router.py').write_text('import fastapi\n')

    returncode, output = _lint_imports(root)

    assert returncode != 0, output
    assert 'harmony.core.leak -> harmony.api.router' in output
