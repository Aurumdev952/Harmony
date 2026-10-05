'''Per-deployment configuration, `config/<code>/`, loaded once per process (BE-2).'''

import dataclasses
import functools
import importlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Tuple

# The scaffold new deployments copy. It loads, but it is not a deployment.
TEMPLATE = 'template'


@dataclasses.dataclass(frozen=True)
class Deployment:
    '''The modules of `config/<code>/`, in the order the legacy loader imported
    them. They are the objects `config.<module>` aliases when ZEN_ENV is `code`.'''

    code: str
    aggregation_rules: ModuleType
    aggregation: ModuleType
    calculated_indicators: ModuleType
    data_status: ModuleType
    datatypes: ModuleType
    druid: ModuleType
    filters: ModuleType
    general: ModuleType
    indicators: ModuleType
    pipeline_sources: ModuleType
    ui: ModuleType


MODULES = tuple(field.name for field in dataclasses.fields(Deployment))[1:]


def _config_root() -> Path:
    # find_spec rather than `import config`: config/__init__.py imports this module.
    spec = importlib.util.find_spec('config')
    if spec is None or spec.origin is None:
        raise ModuleNotFoundError('config is not importable', name='config')
    return Path(spec.origin).parent


def deployment_codes() -> Tuple[str, ...]:
    '''Every directory under config/ with a general.py, except the template.'''
    return tuple(
        sorted(
            path.parent.name
            for path in _config_root().glob('*/general.py')
            if path.parent.name != TEMPLATE
        )
    )


@functools.lru_cache(maxsize=None)
def _load(code: str) -> Deployment:
    modules = [importlib.import_module(f'config.{code}.{name}') for name in MODULES]
    return Deployment(code, *modules)


def load_deployment(code: str) -> Deployment:
    '''Import `config/<code>/`, once per process.'''
    if code not in deployment_codes():
        raise ValueError(
            f'No deployment {code!r} under config/. '
            f'Valid codes: {list(deployment_codes())}'
        )
    return _load(code)


def load_template() -> Deployment:
    '''Import `config/template/`, to prove the scaffold new deployments copy loads.'''
    return _load(TEMPLATE)
