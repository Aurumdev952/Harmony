# To make importing of config variables throughout the site generalized and not
# restricted to a single country's version of the site , we overwrite the
# config module here with the site specific version.
# This allows us to import from config directly.
# for example: from config.general import NATION_NAME
# and NOT: from config.et.general import NATION_NAME
import glob
import importlib
import importlib.abc
import importlib.machinery
import os
import sys
from types import ModuleType
from typing import Optional, Sequence

# Initialize the set of valid config modules to be the subdirectories of the
# config/ directory.
VALID_MODULES = sorted(
    {
        os.path.basename(os.path.dirname(path))
        for path in glob.glob(os.path.join(os.path.dirname(__file__), '*/general.py'))
        if '/template/general.py' not in path
    }
)

# Config modules we never want to handle importing for
_MODULE_WHITELIST = frozenset(
    {'druid_base', 'system', 'instance', 'locales', 'loader', 'settings'}
).union(VALID_MODULES)


class _AliasLoader(importlib.abc.Loader):
    '''Loads `config.<module>` as the module object of `config.<site>.<module>`,
    so both names share one module.'''

    def __init__(self, target_name: str) -> None:
        self._target_name = target_name
        self._target_spec: Optional[importlib.machinery.ModuleSpec] = None

    def create_module(
        self, spec: importlib.machinery.ModuleSpec
    ) -> Optional[ModuleType]:
        module = importlib.import_module(self._target_name)
        self._target_spec = module.__spec__
        return module

    def exec_module(self, module: ModuleType) -> None:
        # The import system has pointed __spec__ at the alias spec. Restore the
        # site module's own spec so importlib.reload re-executes its file.
        module.__spec__ = self._target_spec


class ConfigImporter(importlib.abc.MetaPathFinder):
    '''Captures all config imports and redirect them to the correct site specific
    version.
    '''

    def __init__(self, site_module: Optional[str]) -> None:
        if site_module is not None:
            site_module = site_module.lower()
            message = f'Invalid ZEN_ENV {site_module} not in {VALID_MODULES}'
            if site_module not in VALID_MODULES:
                raise AssertionError(message)
        self._new_config_module = site_module

    def find_spec(
        self,
        fullname: str,
        path: Optional[Sequence[str]],
        target: Optional[ModuleType] = None,
    ) -> Optional[importlib.machinery.ModuleSpec]:
        if not fullname.startswith('config.'):
            return None
        relative_name = fullname[len('config.') :]
        # Config redirection is only needed if the base config module
        # being imported is not part of the whitelist
        if relative_name.partition('.')[0] in _MODULE_WHITELIST:
            return None
        if self._new_config_module is None:
            raise ModuleNotFoundError(
                f'{fullname} is read from config/<ZEN_ENV>/, but ZEN_ENV was not '
                f'set when config was imported. Valid values: {VALID_MODULES}',
                name=fullname,
            )
        target_name = f'config.{self._new_config_module}.{relative_name}'
        return importlib.machinery.ModuleSpec(fullname, _AliasLoader(target_name))


# ZEN_ENV may be unset so that scripts can import an explicit config, such as
# config.harmony_demo.general.
sys.meta_path.append(ConfigImporter(os.environ.get('ZEN_ENV') or None))
