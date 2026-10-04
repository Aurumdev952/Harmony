'''Flask-Potion wiring: which permission guards each /api2 resource and method,
and that Potion's decision agrees with `is_authorized` for every principal.'''

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import yaml
from flask import Flask, g
from flask_potion import Api
from flask_potion.contrib.principals.needs import HybridItemNeed, HybridRelationshipNeed
from flask_principal import ItemNeed, RoleNeed

from models.python.permissions import DimensionFilter, QueryNeed
from tests.authz.principals import load_identity, principal_specs
from web.server.api import api_models
from web.server.routes.views.authorization import is_authorized

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, 'potion.yaml')) as _stream:
    TABLE = yaml.safe_load(_stream)
ITEM_ID = 7


@pytest.fixture(name='resources', scope='session')
def fixture_resources(app: Flask) -> dict:
    with app.app_context(), pytest.MonkeyPatch.context() as patch:
        patch.setattr(api_models, 'list_query_resource_types', list)
        resource_types = api_models.list_all_resource_types()
        api = Api(app, prefix='/api2')
        for resource in resource_types:
            api.add_resource(resource)
    return {resource.__name__: resource for resource in resource_types}


def _permissions(resource) -> dict:
    return resource.manager._permissions  # pylint: disable=protected-access


def test_every_resource_is_classified(resources):
    classified = set(TABLE['principal_resources']) | set(TABLE['unprotected_resources'])
    assert set(resources) == classified


def test_unprotected_resources_have_no_item_permissions(resources):
    for name in TABLE['unprotected_resources']:
        manager = getattr(resources[name], 'manager', None)
        assert not hasattr(manager, '_permissions'), name


@pytest.mark.parametrize('name', sorted(TABLE['principal_resources']))
def test_method_permissions(name, resources):
    spec = TABLE['principal_resources'][name]
    resource = resources[name]
    assert resource.meta.name == spec['type']
    assert resource.manager.id_attribute == spec['id']

    for method, op in TABLE['methods'].items():
        permission = _permissions(resource)[method]
        via = spec.get('read_via') if method == 'read' else None
        need_type = via['type'] if via else spec['type']
        assert permission.standard_needs == {
            RoleNeed('admin'),
            ItemNeed(op, None, need_type),
        }, method
        (hybrid,) = permission.hybrid_needs
        assert (hybrid.method, hybrid.type) == (op, need_type), method
        if via:
            assert isinstance(hybrid, HybridRelationshipNeed), method
            assert [f.attribute for f in hybrid.fields] == [via['attribute']], method
        else:
            assert type(hybrid) is HybridItemNeed, method


def _item(spec: dict):
    via = spec.get('read_via')
    item = SimpleNamespace(**{spec['id']: ITEM_ID})
    if via:
        setattr(item, via['attribute'], SimpleNamespace(**{via['id']: ITEM_ID}))
    return item


@pytest.mark.parametrize('principal', sorted(principal_specs()))
def test_potion_agrees_with_is_authorized(principal, resources, request_ctx):
    load_identity(principal_specs()[principal])
    disagreements = []
    for name, spec in TABLE['principal_resources'].items():
        for method, op in TABLE['methods'].items():
            via = spec.get('read_via') if method == 'read' else None
            need_type = via['type'] if via else spec['type']
            permission = _permissions(resources[name])[method]
            for item, item_id in ((None, None), (_item(spec), ITEM_ID)):
                potion = permission.can(item)
                flask = is_authorized(op, need_type, item_id, log_request=False)
                if potion != flask:
                    disagreements.append((name, method, item_id, potion, flask))
    assert not disagreements


def test_three_dimension_query_need_breaks_potion_list_filtering(
    resources, request_ctx
):
    '''Potion matches identity needs to the 3-tuple ItemNeed prototype by length,
    so a QueryNeed over exactly three dimensions is zipped and raises. Only an
    explicit-needs token whose account is admin can carry one (see WP-2b
    findings).'''
    load_identity(principal_specs()['no_roles'])
    g.identity.provides.add(
        QueryNeed([DimensionFilter(d, all_values=True) for d in ('a', 'b', 'c')])
    )
    read = _permissions(resources['DashboardResource'])['read']
    (hybrid,) = read.hybrid_needs
    with pytest.raises(TypeError):
        list(hybrid.identity_get_item_needs())
