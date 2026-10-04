"""The environment built from uv.lock imports the app's packages and git dependencies."""

import importlib

import pytest

MODULES = [
    "data.query.models",
    "db.druid.query_builder",
    "models.alchemy.user",
    "web.server.routes",
    "pipeline",
    "log",
    "flask_potion",
    "pydruid.client",
    "pylib.base.flags",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)
