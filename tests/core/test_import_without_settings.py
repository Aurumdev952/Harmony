'''Query-engine modules import without deployment settings (INV-8).

`config.settings` refuses to load without DEFAULT_SECRET_KEY and DRUID_HOST.
Tools, migrations and the locked-environment check import these modules in a
bare environment, so nothing they reach may load settings at import time.
'''

import os
import subprocess
import sys
from pathlib import Path

import pytest

MODULES = [
    'db.druid.util',
    'db.druid.query_builder',
    'data.query.models',
    'data.validation.metrics.datatypes',
    'util.fiscal_calendar',
    'util.ethiopian_calendar.ethiopian_calendar',
    'util.stat_month_calendar',
]

UNSET = ('DEFAULT_SECRET_KEY', 'DRUID_HOST', 'ZEN_ENV')


@pytest.mark.parametrize('module', MODULES)
def test_module_imports_without_settings(module):
    environment = {k: v for k, v in os.environ.items() if k not in UNSET}
    imported = subprocess.run(
        [sys.executable, '-c', f'import {module}'],
        env=environment,
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr
