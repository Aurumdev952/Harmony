'''Builds Flask-Principal identities for the principals in principals.yaml.

Needs come from the production code: `BaseUserMixin.enumerate_permissions` over
stand-in role, group and ACL rows, then `signal_handlers.on_identity_loaded`,
which adds the default needs and applies JWT narrowing. Only the inputs those
functions read from the database, the configuration store and the JWT are
replaced.
'''

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from functools import cache
from types import SimpleNamespace
from unittest import mock

import yaml
from flask import g
from flask_principal import AnonymousIdentity, Identity

from models.alchemy.permission import ResourceTypeEnum
from models.alchemy.query_policy.model import QueryPolicy
from models.alchemy.user.base_user import BaseUserMixin
from web.server.security import permissions as permissions_module
from web.server.security import signal_handlers

_HERE = os.path.dirname(__file__)
SIGNED_IN_USER_ID = 42


def _load(name: str) -> dict:
    with open(os.path.join(_HERE, name)) as stream:
        return yaml.safe_load(stream)


SEED = _load('seed.yaml')
PRINCIPALS_FILE = _load('principals.yaml')
RESOURCE_TYPES = {int(k): v for k, v in PRINCIPALS_FILE['resources'].items()}


@dataclass(frozen=True)
class PrincipalSpec:
    name: str
    signed_in: bool = True
    public_access: bool = False
    roles: tuple = ()
    groups: tuple = ()
    acls: tuple = ()
    sitewide_acls: tuple = ()
    jwt: dict | None = None
    tags: frozenset = field(default_factory=frozenset)


def _spec(name: str, raw: dict) -> PrincipalSpec:
    return PrincipalSpec(
        name=name,
        signed_in=raw.get('signed_in', True),
        public_access=raw.get('public_access', False),
        roles=tuple(raw.get('roles', ())),
        groups=tuple(raw.get('groups', ())),
        acls=tuple(raw.get('acls', ())),
        sitewide_acls=tuple(raw.get('sitewide_acls', ())),
        jwt=raw.get('jwt'),
        tags=frozenset(raw.get('tags', ())),
    )


@cache
def principal_specs() -> dict:
    specs = {}
    for role_name in SEED['roles']:
        tags = {'signed_in'} | ({'superuser'} if role_name == 'admin' else set())
        specs[f'role:{role_name}'] = PrincipalSpec(
            name=f'role:{role_name}', roles=(role_name,), tags=frozenset(tags)
        )
    for name, raw in PRINCIPALS_FILE['principals'].items():
        assert name not in specs, f'duplicate principal {name}'
        specs[name] = _spec(name, raw or {})
    return specs


def _resource_type(type_name: str) -> SimpleNamespace:
    return SimpleNamespace(name=ResourceTypeEnum[type_name.upper()])


def _permission_rows(type_name: str, names) -> list:
    resource_type = _resource_type(type_name)
    return [SimpleNamespace(permission=p, resource_type=resource_type) for p in names]


def resource_role(name: str) -> SimpleNamespace:
    raw = SEED['resource_roles'][name]
    return SimpleNamespace(
        name=name, permissions=_permission_rows(raw['type'], raw['permissions'])
    )


def query_policy(dimension: str, value: str | None) -> QueryPolicy:
    # A transient model instance, never flushed: its `dimension_filters`
    # property is the production one, so no reimplementation here.
    return QueryPolicy(dimension=dimension, dimension_value=value)


def role(name: str) -> SimpleNamespace:
    raw = SEED['roles'][name]
    permissions = []
    for type_name, names in (raw.get('permissions') or {}).items():
        permissions.extend(_permission_rows(type_name, names))
    return SimpleNamespace(
        name=name,
        permissions=permissions,
        query_policies=[query_policy(d, v) for d, v in raw.get('query_policies', [])],
        dashboard_resource_role=resource_role(raw['dashboard'])
        if 'dashboard' in raw
        else None,
        alert_resource_role=resource_role(raw['alert']) if 'alert' in raw else None,
        enable_data_export=raw.get('enable_data_export', False),
    )


def policy_role(name: str, policies) -> SimpleNamespace:
    '''A non-admin role that carries only query policies.'''
    return SimpleNamespace(
        name=name,
        permissions=[],
        query_policies=[query_policy(d, v) for d, v in policies],
        dashboard_resource_role=None,
        alert_resource_role=None,
        enable_data_export=False,
    )


def _resource(resource_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=resource_id, resource_type=_resource_type(RESOURCE_TYPES[resource_id])
    )


def _acl(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        resource=_resource(raw['resource']), resource_role=resource_role(raw['role'])
    )


def _sitewide_acl(raw: dict) -> SimpleNamespace:
    def optional_role(key):
        return resource_role(raw[key]) if raw.get(key) else None

    return SimpleNamespace(
        resource=_resource(raw['resource']),
        registered_resource_role=optional_role('registered'),
        unregistered_resource_role=optional_role('unregistered'),
    )


class _Transaction:
    '''Answers the one query enumerate_permissions makes: all sitewide ACLs.'''

    def __init__(self, sitewide_acls):
        self._sitewide_acls = sitewide_acls

    def find_all_by_fields(self, model, fields):
        assert model.__name__ == 'SitewideResourceAcl' and fields == {}, (model, fields)
        return list(self._sitewide_acls)


class StandInUser(BaseUserMixin):
    '''Stands in for `User` (signed in) and `AnonymousUser` (not signed in).'''

    def __init__(self, spec: PrincipalSpec, policies=(), group_policies=()):
        self.id = SIGNED_IN_USER_ID if spec.signed_in else None
        self.username = f'{spec.name}@authz.invalid'
        self.first_name = 'Authz'
        self.last_name = spec.name
        self._signed_in = spec.signed_in
        self.roles = [role(r) for r in spec.roles]
        if policies:
            self.roles.append(policy_role('policy_holder', policies))
        self.acls = [_acl(a) for a in spec.acls]
        self.groups = [
            SimpleNamespace(
                roles=[role(r) for r in group.get('roles', [])],
                acls=[_acl(a) for a in group.get('acls', [])],
            )
            for group in spec.groups
        ]
        if group_policies:
            self.groups.append(
                SimpleNamespace(
                    roles=[policy_role('group_policy_holder', group_policies)], acls=[]
                )
            )
        self._transaction = _Transaction([_sitewide_acl(a) for a in spec.sitewide_acls])
        self.from_jwt = spec.jwt is not None

    @property
    def is_authenticated(self):
        return self._signed_in

    @property
    def is_active(self):
        # Signed-in principals are active accounts; WP-0k's
        # authentication_required refuses any other.
        return self._signed_in

    def get_permissions(self):
        return set(self.enumerate_permissions(self._transaction))


@contextmanager
def configuration(public_access: bool) -> Iterator[None]:
    '''Replaces the configuration-store read behind `is_public_dashboard_user`.'''

    def get_configuration(key):
        assert key == 'public_access', key
        return public_access

    with mock.patch.object(permissions_module, 'get_configuration', get_configuration):
        yield


def load_identity(spec: PrincipalSpec, policies=(), group_policies=()) -> Identity:
    '''Loads the identity for `spec` the way a request would, inside a request
    context. Leaves it on `g.identity`.

    `policies` go on an extra non-admin role the user holds directly, and
    `group_policies` on a role held through an extra group.
    '''
    user = StandInUser(spec, policies, group_policies)
    identity = Identity(user.id) if spec.signed_in else AnonymousIdentity()
    g.identity = identity
    with ExitStack() as stack:
        stack.enter_context(configuration(spec.public_access))
        stack.enter_context(mock.patch.object(signal_handlers, 'current_user', user))
        stack.enter_context(
            mock.patch.object(
                signal_handlers, 'get_jwt_claims', lambda: dict(spec.jwt or {})
            )
        )
        signal_handlers.on_identity_loaded(None, identity)
    return identity
