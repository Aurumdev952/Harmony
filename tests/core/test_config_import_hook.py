'''`config/__init__.py` redirects `config.<module>` to `config/<ZEN_ENV>/<module>`.

The hook reads ZEN_ENV once, when `config` is first imported, and mutates
`sys.meta_path` and `sys.modules`, so every case runs in a fresh interpreter.
Run with the locked environment (CPython 3.13):

    uv run --locked pytest tests/core
'''

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DEPLOYMENT_DIR = REPO / 'config' / 'harmony_demo'


def probe(code, zen_env='harmony_demo'):
    '''Run `code` in a fresh interpreter at the repository root and return the
    JSON object it passes to `report`.'''
    env = {key: value for key, value in os.environ.items() if key != 'ZEN_ENV'}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    if zen_env is not None:
        env['ZEN_ENV'] = zen_env
    prelude = 'import json, sys\ndef report(**kw): print(json.dumps(kw))\n'
    proc = subprocess.run(
        [
            sys.executable,
            # 3.10 and 3.11 warn when the import system falls back to find_module.
            '-W',
            'error::ImportWarning',
            '-c',
            prelude + textwrap.dedent(code),
        ],
        cwd=REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_redirects_to_deployment_module():
    result = probe(
        '''
        import config
        import config.datatypes as module
        report(
            file=module.__file__,
            name=module.__name__,
            spec_name=module.__spec__.name,
            same_object=sys.modules['config.datatypes']
            is sys.modules['config.harmony_demo.datatypes'],
            parent_attribute=config.datatypes is module,
        )
        '''
    )
    assert result == {
        'file': str(DEPLOYMENT_DIR / 'datatypes.py'),
        'name': 'config.harmony_demo.datatypes',
        'spec_name': 'config.harmony_demo.datatypes',
        'same_object': True,
        'parent_attribute': True,
    }


def test_from_import_and_explicit_import_share_one_module():
    result = probe(
        '''
        import config.harmony_demo.data_status as explicit
        from config import data_status
        from config import calculated_indicators
        import config.harmony_demo.calculated_indicators as explicit_after
        report(
            alias_after_explicit=data_status is explicit,
            explicit_after_alias=calculated_indicators is explicit_after,
        )
        '''
    )
    assert result == {'alias_after_explicit': True, 'explicit_after_alias': True}


@pytest.mark.parametrize('name', ['system', 'locales', 'druid_base'])
def test_whitelisted_modules_are_not_redirected(name):
    result = probe(
        f'''
        import config.{name} as module
        report(
            file=module.__file__,
            name=module.__name__,
            deployment_copy='config.harmony_demo.{name}' in sys.modules,
        )
        '''
    )
    assert result == {
        'file': str(REPO / 'config' / f'{name}.py'),
        'name': f'config.{name}',
        'deployment_copy': False,
    }


def test_whitelisted_name_without_a_file_is_not_redirected():
    result = probe(
        '''
        try:
            import config.instance
        except ModuleNotFoundError as error:
            report(name=error.name)
        '''
    )
    assert result == {'name': 'config.instance'}


def test_top_level_config_file_wins_over_redirect():
    result = probe(
        '''
        import config.utils as module
        report(file=module.__file__, name=module.__name__)
        '''
    )
    assert result == {'file': str(REPO / 'config' / 'utils.py'), 'name': 'config.utils'}


def test_redirected_package_and_its_submodules():
    # The package is aliased. Its submodules are found through the aliased
    # package's __path__ before the hook is asked, so they load under the alias
    # name, as a module object distinct from the explicit deployment import.
    result = probe(
        '''
        import config.indicator_groups.yellow_fever as module
        import config.calculated_indicator_defs.calculated_indicator_defs as defs
        report(
            package_is_alias=sys.modules['config.indicator_groups']
            is sys.modules['config.harmony_demo.indicator_groups'],
            file=module.__file__,
            name=module.__name__,
            defs_file=defs.__file__,
            deployment_copy='config.harmony_demo.indicator_groups.yellow_fever'
            in sys.modules,
        )
        '''
    )
    assert result == {
        'package_is_alias': True,
        'file': str(DEPLOYMENT_DIR / 'indicator_groups' / 'yellow_fever.py'),
        'name': 'config.indicator_groups.yellow_fever',
        'defs_file': str(
            DEPLOYMENT_DIR
            / 'calculated_indicator_defs'
            / 'calculated_indicator_defs.py'
        ),
        'deployment_copy': False,
    }


def test_missing_deployment_module_names_the_redirect_target():
    result = probe(
        '''
        try:
            import config.no_such_module
        except ModuleNotFoundError as error:
            report(name=error.name, aliased='config.no_such_module' in sys.modules)
        '''
    )
    assert result == {'name': 'config.harmony_demo.no_such_module', 'aliased': False}


def test_reload_reexecutes_the_deployment_module_in_place():
    result = probe(
        '''
        import importlib
        import config.datatypes as module
        old_class = module.BaseRowType
        reloaded = importlib.reload(module)
        report(
            same_object=reloaded is module,
            reexecuted=reloaded.BaseRowType is not old_class,
            spec_name=reloaded.__spec__.name,
            file=reloaded.__file__,
            aliases_intact=sys.modules['config.datatypes'] is module
            and sys.modules['config.harmony_demo.datatypes'] is module,
        )
        '''
    )
    assert result == {
        'same_object': True,
        'reexecuted': True,
        'spec_name': 'config.harmony_demo.datatypes',
        'file': str(DEPLOYMENT_DIR / 'datatypes.py'),
        'aliases_intact': True,
    }


def test_zen_env_is_case_insensitive():
    result = probe(
        '''
        import config.data_status as module
        report(name=module.__name__)
        ''',
        zen_env='Harmony_Demo',
    )
    assert result == {'name': 'config.harmony_demo.data_status'}


def test_invalid_zen_env_fails_on_import():
    result = probe(
        '''
        try:
            import config
        except AssertionError as error:
            report(message=str(error))
        ''',
        zen_env='atlantis',
    )
    assert result['message'].startswith("Invalid ZEN_ENV atlantis not in [")


def test_unset_zen_env_allows_explicit_imports_and_explains_redirects():
    result = probe(
        '''
        import config.harmony_demo.data_status
        import config.system
        try:
            import config.datatypes
        except ModuleNotFoundError as error:
            report(name=error.name, message=str(error))
        ''',
        zen_env=None,
    )
    assert result['name'] == 'config.datatypes'
    assert 'ZEN_ENV' in result['message']


@pytest.mark.parametrize(
    'module',
    ['config.database', 'config.harmony_demo.database', 'config.template.database'],
)
def test_database_config_queries_druid_on_first_access_not_on_import(module):
    result = probe(
        f'''
        import os
        import types

        os.environ.setdefault('DEFAULT_SECRET_KEY', 'not-a-secret')
        os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
        calls = []

        class DruidMetadata:
            @staticmethod
            def get_most_recent_datasource(site):
                calls.append(site)
                return 'datasource-for-' + site

        stub = types.ModuleType('db.druid.metadata')
        stub.DruidMetadata = DruidMetadata
        sys.modules['db.druid.metadata'] = stub

        import {module} as database
        on_import = list(calls)
        first = database.DATASOURCE
        from {module} import DATASOURCE
        report(
            site=database.DEPLOYMENT_NAME,
            on_import=on_import,
            first=first,
            again=DATASOURCE,
            calls=calls,
        )
        '''
    )
    site = result.pop('site')
    assert result == {
        'on_import': [],
        'first': f'datasource-for-{site}',
        'again': f'datasource-for-{site}',
        'calls': [site],
    }


def test_missing_datasource_reaches_the_callers_except():
    # data/query_policy/query_policy.py wraps `from config.database import
    # DATASOURCE` in `except MissingDatasourceException`. The lazy lookup must
    # not turn that error into an ImportError.
    result = probe(
        '''
        import os
        import types

        from db.druid.errors import MissingDatasourceException

        os.environ.setdefault('DEFAULT_SECRET_KEY', 'not-a-secret')
        os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
        calls = []

        class DruidMetadata:
            @staticmethod
            def get_most_recent_datasource(site):
                calls.append(site)
                raise MissingDatasourceException(site)

        stub = types.ModuleType('db.druid.metadata')
        stub.DruidMetadata = DruidMetadata
        sys.modules['db.druid.metadata'] = stub

        caught = []
        for _ in range(2):
            try:
                from config.database import DATASOURCE  # noqa: F401
            except MissingDatasourceException:
                caught.append('MissingDatasourceException')
        report(caught=caught, calls=calls)
        '''
    )
    assert result == {
        'caught': ['MissingDatasourceException', 'MissingDatasourceException'],
        'calls': ['harmony_demo', 'harmony_demo'],
    }
