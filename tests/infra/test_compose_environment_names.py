import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def _environment_names(compose_file: Path):
    services = yaml.safe_load(compose_file.read_text()).get('services') or {}
    for service_name, service in services.items():
        environment = (service or {}).get('environment') or []
        if isinstance(environment, dict):
            names = list(environment)
        else:
            names = [str(entry).split('=', 1)[0] for entry in environment]
        for name in names:
            yield service_name, name


@pytest.mark.parametrize(
    'compose_file',
    sorted(REPO_ROOT.glob('docker-compose*.yaml')),
    ids=lambda path: path.name,
)
def test_environment_entries_are_valid_variable_names(compose_file):
    bad = [
        f'{service}: {name!r}'
        for service, name in _environment_names(compose_file)
        if not ENV_NAME.match(name)
    ]
    assert not bad, f'{compose_file.name} sets invalid variable names: {bad}'
