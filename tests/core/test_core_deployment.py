'''`harmony.core.deployment`: the registry of `config/<code>/` and one loader
for every process (BE-2).

Loading runs in fresh interpreters with sockets disabled, so a deployment module
that does network I/O at import fails the test (phase 4a check).
'''

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harmony.core.deployment import Deployment, deployment_codes

REPO = Path(__file__).resolve().parents[2]

# Every module the legacy loader (config/loader.py at ea33d9d) imported and a
# reader reaches through current_app.zen_config or import_configuration_module.
MODULES = [
    'aggregation_rules',
    'aggregation',
    'calculated_indicators',
    'data_status',
    'datatypes',
    'druid',
    'filters',
    'general',
    'indicators',
    'pipeline_sources',
    'ui',
]

PROBE = '''
import importlib, json, socket, sys


def refuse(*args, **kwargs):
    raise OSError('network access during deployment load')


socket.socket.connect = refuse
socket.socket.connect_ex = refuse
socket.socket.sendto = refuse
socket.create_connection = refuse
socket.getaddrinfo = refuse

from harmony.core.deployment import load_deployment, load_template

code, modules = sys.argv[1], json.loads(sys.argv[2])
load = load_template if code == 'template' else lambda: load_deployment(code)
deployment = load()
legacy = __import__(f'config.{code}', fromlist=modules)
print(json.dumps({
    'code': deployment.code,
    'cached': load() is deployment,
    'modules': {name: getattr(deployment, name).__name__ for name in modules},
    'same_as_legacy': [
        name for name in modules if getattr(deployment, name) is getattr(legacy, name)
    ],
    # config.<name> resolves through ZEN_ENV (harmony_demo), not through `code`.
    'same_as_alias': [
        name for name in modules
        if getattr(deployment, name) is importlib.import_module(f'config.{name}')
    ],
}))
'''


def _environment(**extra: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    env.update(
        DEFAULT_SECRET_KEY='tests-core-placeholder-key',
        DRUID_HOST='http://druid.invalid',
        ZEN_ENV='harmony_demo',
        PYTHONDONTWRITEBYTECODE='1',
    )
    env.update(extra)
    return env


def _python(code: str, *args: str, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, '-c', code, *args],
        cwd=REPO,
        env=_environment(**extra),
        capture_output=True,
        text=True,
        check=False,
    )


def test_registry_lists_every_deployment_but_the_template():
    expected = sorted(
        path.parent.name
        for path in (REPO / 'config').glob('*/general.py')
        if path.parent.name != 'template'
    )

    assert deployment_codes() == tuple(expected)
    assert 'harmony_demo' in deployment_codes()


def test_valid_modules_is_the_registry():
    proc = _python('import config, json; print(json.dumps(config.VALID_MODULES))')

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == list(deployment_codes())


def test_deployment_holds_the_modules_the_legacy_loader_exposed():
    fields = [field.name for field in dataclasses.fields(Deployment)]

    assert fields == ['code', *MODULES]


def test_deployment_is_frozen():
    deployment = Deployment('x', *([sys] * len(MODULES)))

    with pytest.raises(dataclasses.FrozenInstanceError):
        deployment.general = os  # type: ignore[misc]


@pytest.mark.parametrize('code', ['harmony_demo', 'template'])
def test_loads_without_network_and_shares_module_objects(code):
    proc = _python(PROBE, code, json.dumps(MODULES))

    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result['code'] == code
    assert result['cached']
    assert result['modules'] == {name: f'config.{code}.{name}' for name in MODULES}
    assert result['same_as_legacy'] == MODULES
    assert result['same_as_alias'] == (MODULES if code == 'harmony_demo' else [])


REFUSED = ['nope', '', '../config/harmony_demo', 'harmony_demo/..', '__pycache__']


@pytest.mark.parametrize('code', [*REFUSED, 'template'])
def test_refuses_an_unknown_code(code):
    proc = _python(
        'import sys\n'
        'from harmony.core.deployment import load_deployment\n'
        'load_deployment(sys.argv[1])\n',
        code,
    )

    assert proc.returncode != 0
    assert 'ValueError' in proc.stderr
    assert 'harmony_demo' in proc.stderr


@pytest.mark.parametrize('code', ['template', *REFUSED])
def test_legacy_loader_refuses_what_is_not_a_deployment(code):
    # The legacy loader failed on these too (ModuleNotFoundError: 'template' was
    # redirected to config.harmony_demo.template by the import hook).
    proc = _python(
        'import sys\n'
        'from config.loader import import_configuration_module\n'
        'import_configuration_module(sys.argv[1] or "nope")\n',
        code,
    )

    assert proc.returncode != 0
    assert 'ValueError' in proc.stderr


WEB_FRAMEWORKS = ('flask', 'fastapi', 'starlette', 'werkzeug')


@pytest.mark.parametrize('code', [*deployment_codes(), 'template'])
def test_loading_a_deployment_imports_no_web_framework(code):
    # The BE-1 contract cannot follow load_deployment's importlib.import_module,
    # so this checks what a deployment actually pulls in, in a fresh interpreter.
    load = 'load_template()' if code == 'template' else f'load_deployment({code!r})'
    proc = _python(
        'import json, sys\n'
        'from harmony.core.deployment import load_deployment, load_template\n'
        f'{load}\n'
        'print(json.dumps(sorted({m.split(".")[0] for m in sys.modules})))\n'
    )

    assert proc.returncode == 0, proc.stderr
    loaded = set(json.loads(proc.stdout.strip().splitlines()[-1]))
    assert loaded.isdisjoint(WEB_FRAMEWORKS), sorted(loaded & set(WEB_FRAMEWORKS))


def test_legacy_loader_returns_the_deployment():
    proc = _python(
        'from config.loader import import_configuration_module\n'
        'from harmony.core.deployment import load_deployment\n'
        'explicit = import_configuration_module("harmony_demo")\n'
        'assert explicit is load_deployment("harmony_demo"), explicit\n'
        'assert import_configuration_module() is explicit\n'
        'print(explicit.general.DEPLOYMENT_NAME)\n'
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == 'harmony_demo'


def test_legacy_loader_refuses_an_unset_zen_env():
    proc = _python(
        'from config.loader import import_configuration_module\n'
        'import_configuration_module()\n',
        ZEN_ENV='',
    )

    assert proc.returncode != 0
    assert 'ValueError' in proc.stderr
