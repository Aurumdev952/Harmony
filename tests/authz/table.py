'''Expands decisions.yaml into (principal, permission, type, id, expected) rows.'''

from __future__ import annotations

import os
from typing import NamedTuple

import yaml

from tests.authz.principals import principal_specs

_HERE = os.path.dirname(__file__)


class Row(NamedTuple):
    principal: str
    permission: str
    resource_type: str
    resource_id: int | None
    allowed: bool
    used_by: str

    @property
    def id(self) -> str:
        target = (
            self.resource_type
            if self.resource_id is None
            else f'{self.resource_type}:{self.resource_id}'
        )
        verdict = 'allow' if self.allowed else 'deny'
        return f'{self.principal}|{self.permission}|{target}|{verdict}'


def _expand(names: list, specs: dict) -> set:
    expanded = set()
    for name in names:
        if name.startswith('tag:'):
            tagged = {n for n, s in specs.items() if name[4:] in s.tags}
            assert tagged, f'no principal carries {name}'
            expanded |= tagged
        else:
            assert name in specs, f'unknown principal {name}'
            expanded.add(name)
    return expanded


def load_checks() -> list:
    with open(os.path.join(_HERE, 'decisions.yaml')) as stream:
        return yaml.safe_load(stream)['checks']


def rows() -> list:
    specs = principal_specs()
    result = []
    seen = set()
    for check in load_checks():
        permission, resource_type, resource_id = check['check']
        key = (permission, resource_type, resource_id)
        assert key not in seen, f'duplicate check {key}'
        seen.add(key)
        allowed = _expand(check['allow'], specs)
        result.extend(
            Row(principal, *key, principal in allowed, check['used_by'])
            for principal in specs
        )
    return result
