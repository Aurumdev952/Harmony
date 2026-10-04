from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from tests.authz.http.stack import Stack

_HERE = os.path.dirname(__file__)


def pytest_collection_modifyitems(config, items):
    del config
    skip = pytest.mark.skip(reason='set AUTHZ_BASE_URL; see tests/authz/stack.sh')
    for item in items:
        if str(item.fspath).startswith(_HERE):
            item.add_marker(pytest.mark.authz_http)
            if not os.environ.get('AUTHZ_BASE_URL'):
                item.add_marker(skip)


@pytest.fixture(name='stack', scope='session')
def fixture_stack() -> Iterator[Stack]:
    stack = Stack.from_env()
    yield stack
    stack.cleanup()
