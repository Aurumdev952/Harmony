'''The migrations still seed exactly the roles the pure layer models (seed.yaml).'''

from __future__ import annotations

from tests.authz.principals import SEED

RESOURCE_TYPES = {
    1: 'site',
    2: 'dashboard',
    3: 'user',
    4: 'group',
    6: 'alert',
    7: 'role',
}


def _as_seed(role: dict) -> dict:
    entry: dict = {}
    permissions: dict = {}
    for permission in role['permissions']:
        type_name = RESOURCE_TYPES[permission['resource_type_id']]
        permissions.setdefault(type_name, []).append(permission['permission'])
    if permissions:
        entry['permissions'] = {t: sorted(p) for t, p in permissions.items()}
    if role['dashboardResourceRoleName']:
        entry['dashboard'] = role['dashboardResourceRoleName']
    if role['alertResourceRoleName']:
        entry['alert'] = role['alertResourceRoleName']
    if role['queryPolicies']:
        entry['query_policies'] = sorted(
            [p['dimension'], p['dimensionValue']] for p in role['queryPolicies']
        )
    if role['dataExport']:
        entry['enable_data_export'] = True
    return entry


def _normalised_seed(raw: dict) -> dict:
    entry = dict(raw)
    if 'permissions' in entry:
        entry['permissions'] = {t: sorted(p) for t, p in entry['permissions'].items()}
    if 'query_policies' in entry:
        entry['query_policies'] = sorted(entry['query_policies'])
    return entry


def test_seeded_roles_match_seed_yaml(stack):
    live = {
        role['name']: _as_seed(role)
        for role in stack.admin_json('GET', '/api2/role?per_page=100')
        if not role['name'].startswith('authz_')
    }
    expected = {name: _normalised_seed(raw) for name, raw in SEED['roles'].items()}
    assert live == expected
