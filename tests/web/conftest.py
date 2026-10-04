from __future__ import annotations

import os
from collections.abc import Callable

import pytest
from flask import Flask

# config/settings.py and the config loader read these at import time; the values are
# test-only placeholders, and harmony_demo is the deployment checked into the repo.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-web-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('ZEN_ENV', 'harmony_demo')

_HERE = os.path.dirname(__file__)


@pytest.fixture(name='bare_flask_app')
def fixture_bare_flask_app() -> Callable[[], Flask]:
    # Explicit paths: Flask 1.0 cannot locate a module loaded by pytest's rewrite hook.
    return lambda: Flask('tests.web', root_path=_HERE, instance_path=_HERE)
