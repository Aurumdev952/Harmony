'''What a caller may attach to a group or put into a role.

Holding `edit_resource` on a group or a role lets a caller change it, not
decide what its members receive. A non-superuser may attach or confer only
grants it already holds: roles, query policies and data export. Permissions
and resource roles on a role pass the `update_permissions` gate, and a
resource role on a resource needs `update_users` there. Grants a group or
role already has may be sent again unchanged.
'''

from __future__ import annotations

from collections.abc import Iterable
from typing import NoReturn

from flask import g
from flask_login import current_user
from werkzeug.exceptions import BadRequest, Forbidden

from models.alchemy.permission import Resource, ResourceRole, Role
from models.alchemy.user.web_base_user import BaseWebUserMixin
from web.server.potion.access import get_id_from_uri
from web.server.routes.views.authorization import is_authorized
from web.server.routes.views.core import try_get_role_and_resource
from web.server.routes.views.query_policy import construct_query_need_from_policy
from web.server.security.permissions import SuperUserPermission
from web.server.util.util import get_user_string


def refuse_grant(description: str, detail: str = '') -> NoReturn:
    '''`detail` goes to the audit line only, for names the caller may not list.'''
    # The log formatter drops LoggerAdapter extras, so the caller goes in the text.
    g.request_logger.warning(
        'Refused grant by \'%s\': %s %s',
        get_user_string(current_user),
        description,
        detail,
    )
    raise Forbidden(description=description)


def _is_superuser() -> bool:
    # The identity, not the account: a narrowed JWT on an admin account loses
    # RoleNeed('admin') and must not grant as an admin.
    return SuperUserPermission().can()


def _account_needs() -> set:
    '''Needs are compared by equality, never by `QueryNeed` containment, which
    does not follow how policies combine into the Druid filter: a broader held
    policy is not trusted to cover a narrower one.
    '''
    # The identity adds the default needs; the account's own needs are added
    # because a JWT session can narrow query needs into intersections that no
    # longer compare equal to the policies they came from.
    return g.identity.provides | current_user.get_permissions()


def _exports_data() -> bool:
    return any(role.enable_data_export for role in current_user.get_all_roles())


def held_roles_from_uris(role_uris: Iterable[str]) -> list[Role]:
    '''Resolves role URIs, keeping the roles the caller holds, as the
    `RoleResourceManager` filter does. URIs naming no role are skipped; a role
    the caller does not hold is refused.
    '''
    try:
        role_ids = {get_id_from_uri(uri) for uri in role_uris}
    except (AttributeError, TypeError, ValueError) as error:
        raise BadRequest(description='Roles must be a list of role URIs.') from error
    requested = Role.query.filter(Role.id.in_(role_ids)).all()
    if _is_superuser():
        return requested
    held_ids = {
        role.id for role in current_user.get_all_roles() if role.name != 'admin'
    }
    not_held = sorted(
        (role for role in requested if role.id not in held_ids), key=lambda r: r.id
    )
    if not_held:
        refuse_grant(
            'You may only attach roles you hold yourself. Not held: '
            f'{[f"/api2/role/{role.id}" for role in not_held]}.',
            f'Role names: {[role.name for role in not_held]}.',
        )
    return requested


def verify_acl_grants(
    acls: Iterable[dict], existing_acls: Iterable
) -> list[tuple[ResourceRole, Resource]]:
    '''Resolves a group's ACL list. Each new resource role on a resource needs
    `update_users` on that resource, as sharing it through
    `/api2/resource/<id>/roles` does. Returns the resolved pairs, so the write
    stores exactly what was authorised.
    '''
    existing = {(acl.resource_role_id, acl.resource_id) for acl in existing_acls}
    grants = []
    for acl in acls:
        resource_name = acl['resource'].get('name')
        if not resource_name:
            # A group ACL without a resource breaks need building for every member.
            raise BadRequest(description='Each group ACL must name a resource.')
        resource_role, _, resource = try_get_role_and_resource(
            acl['resourceRole']['name'],
            acl['resource'].get('resourceType'),
            resource_name,
        )
        grants.append((resource_role, resource))
        if (resource_role.id, resource.id) in existing:
            continue
        resource_type = resource.resource_type.name.name
        if not is_authorized('update_users', resource_type, resource.id):
            refuse_grant(
                f'Granting \'{resource_role.name}\' on {resource_type} '
                f'\'{resource.name}\' needs the \'update_users\' permission on it.'
            )
    return grants


def verify_role_grants(new_role: dict, role: Role | None = None) -> None:
    '''Checks a role create (`role` is None) or update. `new_role` is the output
    of `build_role`. Every holder of the role, the caller included, gains what
    is added.
    '''
    gated = [
        name
        for name, current, requested in (
            (
                'permissions',
                {p.id for p in role.permissions} if role else set(),
                {p.id for p in new_role['permissions']},
            ),
            (
                'dashboard resource role',
                role.dashboard_resource_role_id if role else None,
                new_role['dashboard_resource_role_id'],
            ),
            (
                'alert resource role',
                role.alert_resource_role_id if role else None,
                new_role['alert_resource_role_id'],
            ),
        )
        if current != requested
    ]
    if gated and not is_authorized(
        'update_permissions', 'role', role.id if role else None
    ):
        refuse_grant(
            f'Changing the {", ".join(gated)} of a role needs the '
            '\'update_permissions\' permission.'
        )

    if _is_superuser():
        return
    current_policy_ids = {q.id for q in role.query_policies} if role else set()
    account_needs = _account_needs()
    not_held = [
        policy
        for policy in new_role['query_policies']
        if policy.id not in current_policy_ids
        and construct_query_need_from_policy(policy) not in account_needs
    ]
    if not_held:
        refuse_grant(
            'You may only add query policies you hold yourself. Not held: '
            f'{sorted((p.dimension, p.dimension_value or "*") for p in not_held)}.'
        )
    exported = role.enable_data_export if role else False
    if new_role['enable_data_export'] and not exported and not _exports_data():
        refuse_grant('You may only allow data export if you can export data yourself.')


def holds_everything_in(role: Role) -> bool:
    '''Whether the caller's account already holds every need `role` grants, and
    data export if the role allows it.
    '''
    account_needs = _account_needs()
    # pylint: disable=protected-access
    role_needs = BaseWebUserMixin._build_role_needs([role])
    if not all(need in account_needs for need in role_needs):
        return False
    return not role.enable_data_export or _exports_data()
