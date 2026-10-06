from __future__ import annotations

import os
from collections.abc import Callable

import pytest
from flask import Flask

from tests.flask_isolation import restored_flask_globals
from tests.throwaway_postgres import (  # noqa: F401
    fixture_postgres_database,
    fixture_postgres_server,
)

# config/settings.py and the config loader read these at import time; the values are
# test-only placeholders, and harmony_demo is the deployment checked into the repo.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-web-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('ZEN_ENV', 'harmony_demo')

_HERE = os.path.dirname(__file__)


@pytest.fixture(autouse=True)
def _no_flask_state_leaks():
    # Building the full app binds Potion resources to its Api, and some tests leave
    # an app context pushed; either breaks later tests in the same process.
    with restored_flask_globals():
        yield


@pytest.fixture(name='bare_flask_app')
def fixture_bare_flask_app() -> Callable[[], Flask]:
    # Explicit paths: Flask 1.0 cannot locate a module loaded by pytest's rewrite hook.
    return lambda: Flask('tests.web', root_path=_HERE, instance_path=_HERE)
