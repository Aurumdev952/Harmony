'''Flask-Potion wiring: which permission guards each /api2 resource and method,
and that Potion's decision agrees with `is_authorized` for every principal.'''

from __future__ import annotations

import dataclasses
import os
from types import SimpleNamespace

import pytest
import yaml
from flask import Flask, g
from flask_potion import Api
from flask_potion.contrib.principals.needs import HybridItemNeed, HybridRelationshipNeed
from flask_principal import ItemNeed, RoleNeed

from models.python.permissions import QueryNeed
from tests.authz.principals import load_identity, principal_specs
from tests.authz.table import load_checks
from web.server.api import api_models
from web.server.routes.views.authorization import is_authorized

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, 'potion.yaml')) as _stream:
    TABLE = yaml.safe_load(_stream)

ID_COLUMNS = ('id', 'key', 'resource_id', 'authorization_resource_id')
UNHELD_ITEM_ID = 901
DECOY_ID = 900
WRITE_METHODS = ('create', 'update', 'delete')


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


def test_every_potion_operation_has_a_recorded_decision():
    recorded = {(perm, type_) for perm, type_, _ in (c['check'] for c in load_checks())}
    missing = set()
    for spec in TABLE['principal_resources'].values():
        for method, op in TABLE['methods'].items():
            need_type = spec['type']
            if method == 'read' and 'read_via' in spec:
                need_type = spec['read_via']['type']
            if (op, need_type) not in recorded:
                missing.add((op, need_type))
    assert not missing


def _stand_in(id_attribute: str, item_id: int) -> SimpleNamespace:
    '''An item whose `id_attribute` is `item_id` and whose other id columns
    hold a value no principal has needs on.'''
    item = SimpleNamespace(**{column: DECOY_ID for column in ID_COLUMNS})
    setattr(item, id_attribute, item_id)
    return item


def _needs_held(op: str, need_type: str) -> set:
    return {
        need.value
        for need in g.identity.provides
        if isinstance(need, ItemNeed)
        and need.method == op
        and need.type == need_type
        and need.value is not None
    }


@pytest.mark.parametrize('principal', sorted(principal_specs()))
def test_potion_reads_agree_with_is_authorized(principal, resources, request_ctx):
    '''List and item GETs never evaluate an item: everything when the sitewide
    check passes, otherwise the ids held with `view_resource` on the type.'''
    load_identity(principal_specs()[principal])
    disagreements = []
    for name, spec in TABLE['principal_resources'].items():
        need_type = spec.get('read_via', {}).get('type', spec['type'])
        read = _permissions(resources[name])['read']
        sitewide = is_authorized('view_resource', need_type, None, log_request=False)
        if read.can() != sitewide:
            disagreements.append((name, 'sitewide', read.can(), sitewide))
        if sitewide:
            continue
        (hybrid,) = read.hybrid_needs
        listed = set(hybrid.identity_get_item_needs())
        if listed != _needs_held('view_resource', need_type):
            disagreements.append((name, 'ids', listed))
    assert not disagreements


@pytest.mark.parametrize('name', sorted(TABLE['principal_resources']))
def test_list_filter_column(name, resources):
    '''The SQL rule for reads: held ids are matched against this column.'''
    spec = TABLE['principal_resources'][name]
    via = spec.get('read_via')
    (hybrid,) = _permissions(resources[name])['read'].hybrid_needs
    target = hybrid.fields[-1].target if via else resources[name]
    column = via['list_filter_id'] if via else spec['id']
    assert target.manager.id_attribute == column
    # pylint: disable-next=protected-access
    expression = str(target.manager._expression_for_ids([11]))
    assert expression.split(' IN ')[0].endswith(f'.{column}'), expression


@pytest.mark.parametrize('principal', sorted(principal_specs()))
def test_potion_writes_agree_with_is_authorized(principal, resources, request_ctx):
    '''Create, update and delete evaluate the item against its id attribute.'''
    load_identity(principal_specs()[principal])
    disagreements = []
    for name, spec in TABLE['principal_resources'].items():
        item_id = spec.get('item_id', UNHELD_ITEM_ID)
        item = _stand_in(spec['id'], item_id)
        for method in WRITE_METHODS:
            op = TABLE['methods'][method]
            permission = _permissions(resources[name])[method]
            for target, target_id in ((None, None), (item, item_id)):
                potion = permission.can(target)
                flask = is_authorized(op, spec['type'], target_id, log_request=False)
                if potion != flask:
                    disagreements.append((name, method, target_id, potion, flask))
    assert not disagreements


@pytest.mark.usefixtures('request_ctx')
def test_every_item_id_is_held_as_a_write_need():
    '''Otherwise the per-item write comparison above is vacuous: Potion and
    is_authorized would both deny every principal.'''
    write_ops = {TABLE['methods'][method] for method in WRITE_METHODS}
    item_ids = {
        name: (spec['type'], spec['item_id'])
        for name, spec in TABLE['principal_resources'].items()
        if 'item_id' in spec
    }
    held = set()
    for spec in principal_specs().values():
        load_identity(spec)
        for name, (need_type, item_id) in item_ids.items():
            if any(item_id in _needs_held(op, need_type) for op in write_ops):
                held.add(name)
    assert item_ids
    assert held == set(item_ids)


def test_alert_notification_item_check_uses_the_parent_primary_key(
    resources, request_ctx
):
    '''Finding "Alert read_via", pinned as today. The item-level read check
    resolves the parent alert definition's own `id`, not the
    `authorization_resource_id` that ACLs and the list filter use. No HTTP
    route evaluates it today. Owner: accept until WP-5f; WP-4e's can() models
    it as the parent alert's resource.'''
    via = TABLE['principal_resources']['AlertNotificationResource']['read_via']
    load_identity(principal_specs()['alert_owner'])
    read = _permissions(resources['AlertNotificationResource'])['read']
    (hybrid,) = read.hybrid_needs
    parent = _stand_in('authorization_resource_id', via['item_id'])
    notification = SimpleNamespace(**{via['attribute']: parent})

    assert hybrid(notification) == ItemNeed(
        'view_resource', getattr(parent, via['item_check_id']), via['type']
    )
    assert via['item_id'] in set(hybrid.identity_get_item_needs())
    assert read.can(notification) is False


def test_three_dimension_query_need_breaks_potion_list_filtering(
    resources, request_ctx
):
    '''P3, pinned as today. An admin account using a token with an explicit
    `needs` list keeps its composite `query_needs` verbatim. One over exactly
    three dimensions matches Potion's 3-tuple ItemNeed prototype by length, so
    list filtering raises. Owner: WP-4e.'''
    spec = dataclasses.replace(
        principal_specs()['role:admin'],
        jwt={
            'needs': [['view_resource', 7, 'dashboard']],
            'query_needs': [{'source': {}, 'StateName': {}, 'MunicipalityName': {}}],
        },
    )
    load_identity(spec)
    assert any(isinstance(n, QueryNeed) and len(n) == 3 for n in g.identity.provides)
    (hybrid,) = _permissions(resources['DashboardResource'])['read'].hybrid_needs
    with pytest.raises(TypeError):
        list(hybrid.identity_get_item_needs())
