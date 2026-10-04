'''What a caller may attach to a group or put into a role.

Holding `edit_resource` on a group or a role lets a caller change it, not
decide what its members receive. A caller may grant only what it could grant
directly: roles it holds, resource roles on resources it may share, and
permissions only through the `update_permissions` gate.
'''

from __future__ import annotations

from collections.abc import Iterable
from typing import NoReturn

from flask import g
from flask_login import current_user
from werkzeug.exceptions import Forbidden

from models.alchemy.permission import Role
from models.alchemy.user.web_base_user import BaseWebUserMixin
from web.server.potion.access import get_id_from_uri
from web.server.potion.managers import roles_held_by
from web.server.routes.views.authorization import is_authorized
from web.server.routes.views.core import try_get_role_and_resource
from web.server.util.util import get_user_string


def refuse_grant(description: str) -> NoReturn:
    # The log formatter drops LoggerAdapter extras, so the caller goes in the text.
    g.request_logger.warning(
        'Refused grant by \'%s\': %s', get_user_string(current_user), description
    )
    raise Forbidden(description=description)


def held_roles_from_uris(role_uris: Iterable[str]) -> list[Role]:
    '''Resolves role URIs through the same filter as `RoleResourceManager`.
    URIs naming no role are skipped; a role the caller does not hold is refused.
    '''
    role_ids = {get_id_from_uri(uri) for uri in role_uris}
    held = roles_held_by(current_user, Role.query.filter(Role.id.in_(role_ids))).all()
    not_held = Role.query.filter(
        Role.id.in_(role_ids - {role.id for role in held})
    ).all()
    if not_held:
        names = sorted(role.name for role in not_held)
        refuse_grant(f'You may only attach roles you hold yourself. Not held: {names}.')
    return held


def verify_acl_grants(acls: Iterable[dict], existing_acls: Iterable) -> None:
    '''Each new resource role on a resource needs `update_users` on that
    resource, as sharing it through `/api2/resource/<id>/roles` does. Grants
    the holder already has may be sent again unchanged.
    '''
    existing = {(acl.resource_role_id, acl.resource_id) for acl in existing_acls}
    for acl in acls:
        resource_type = acl['resource'].get('resourceType')
        resource_role, _, resource = try_get_role_and_resource(
            acl['resourceRole']['name'], resource_type, acl['resource'].get('name')
        )
        resource_id = resource.id if resource else None
        if (resource_role.id, resource_id) in existing:
            continue
        if not is_authorized('update_users', resource_type, resource_id):
            target = f'\'{resource.name}\'' if resource else 'every resource'
            refuse_grant(
                f'Granting \'{resource_role.name}\' on {resource_type} {target} needs '
                'the \'update_users\' permission on it.'
            )


def _require_update_permissions(role_id: int | None, changed: list[str]) -> None:
    if changed and not is_authorized('update_permissions', 'role', role_id):
        refuse_grant(
            f'Changing the {", ".join(changed)} of a role needs the '
            '\'update_permissions\' permission.'
        )


def verify_new_role_grants(new_role: dict) -> None:
    '''`new_role` is the output of `build_role`.'''
    _require_update_permissions(
        None,
        [
            name
            for name, value in (
                ('permissions', new_role['permissions']),
                ('dashboard resource role', new_role['dashboard_resource_role_id']),
                ('alert resource role', new_role['alert_resource_role_id']),
            )
            if value
        ],
    )


def verify_role_update_grants(role: Role, new_role: dict) -> None:
    '''Every holder of `role`, the caller included, gains what an update adds.'''
    _require_update_permissions(
        role.id,
        [
            name
            for name, current, requested in (
                (
                    'permissions',
                    {p.id for p in role.permissions},
                    {p.id for p in new_role['permissions']},
                ),
                (
                    'dashboard resource role',
                    role.dashboard_resource_role_id,
                    new_role['dashboard_resource_role_id'],
                ),
                (
                    'alert resource role',
                    role.alert_resource_role_id,
                    new_role['alert_resource_role_id'],
                ),
                (
                    'query policies',
                    {q.id for q in role.query_policies},
                    {q.id for q in new_role['query_policies']},
                ),
                (
                    'data export',
                    role.enable_data_export,
                    new_role['enable_data_export'],
                ),
            )
            if current != requested
        ],
    )


def holds_everything_in(role: Role) -> bool:
    '''Whether the caller's account already holds every need `role` grants, and
    data export if the role allows it.
    '''
    # The identity adds the default needs; the account's own needs are added
    # because a JWT session can narrow query needs into intersections that no
    # longer compare equal to the policies they came from.
    held = g.identity.provides | current_user.get_permissions()
    # pylint: disable=protected-access
    if not all(need in held for need in BaseWebUserMixin._build_role_needs([role])):
        return False
    return not role.enable_data_export or any(
        held.enable_data_export for held in current_user.get_all_roles()
    )
