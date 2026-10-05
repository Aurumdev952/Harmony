from __future__ import annotations

import logging
import os
from collections.abc import Iterator

import pytest

# The config modules read these at import time; the values are test-only
# placeholders, and harmony_demo is the deployment checked into the repo.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-authz-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('RENDERBOT_EMAIL', 'renderbot@authz.invalid')
os.environ.setdefault('URLBOX_API_URL', 'http://urlbox.invalid')

# pylint: disable=wrong-import-position
from flask import Flask, g

from config.loader import import_configuration_module

_HERE = os.path.dirname(__file__)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        'markers',
        'authz_http: runs against a live stack; needs AUTHZ_BASE_URL '
        '(see tests/authz/stack.sh)',
    )


@pytest.fixture(name='app', scope='session')
def fixture_app() -> Flask:
    # Explicit paths: Flask 1.0 cannot locate a module loaded by pytest's rewrite hook.
    app = Flask('tests.authz', root_path=_HERE, instance_path=_HERE)
    app.zen_config = import_configuration_module('harmony_demo')
    return app


@pytest.fixture(name='request_ctx')
def fixture_request_ctx(app: Flask) -> Iterator[None]:
    with app.test_request_context('/'):
        g.request_logger = logging.LoggerAdapter(logging.getLogger('tests.authz'), {})
        yield
