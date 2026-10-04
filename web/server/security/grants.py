'''What a caller may give a group, a user or a role.

Holding `edit_resource` on a group, a user or a role lets a caller change it,
not decide what it receives. A non-superuser may attach or confer only grants
it already holds: roles, membership of its own groups, query policies and
data export. Permissions and resource roles on a role pass the
`update_permissions` gate, and a resource role on a resource needs
`update_users` there. Grants the target already has may be sent again
unchanged.
'''

from __future__ import annotations

from collections.abc import Iterable
from typing import NoReturn

from flask import g
from flask_login import current_user
from werkzeug.exceptions import BadRequest, Forbidden

from models.alchemy.permission import Resource, ResourceRole, Role
from models.alchemy.security_group import Group
from models.alchemy.user.web_base_user import BaseWebUserMixin
from web.server.data.data_access import get_db_adapter
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


def _ids_from_uris(uris: Iterable[str], kind: str) -> set[int]:
    try:
        return {get_id_from_uri(uri) for uri in uris}
    except (AttributeError, TypeError, ValueError) as error:
        raise BadRequest(description=f'Expected a list of {kind} URIs.') from error


def held_roles_from_uris(
    role_uris: Iterable[str], existing: Iterable = ()
) -> list[Role]:
    '''Resolves role URIs for a group or user that already has the `existing`
    roles. Each other role must be one the caller holds, as the
    `RoleResourceManager` filter has it. URIs naming no role are skipped.
    '''
    role_ids = _ids_from_uris(role_uris, 'role')
    session = get_db_adapter().session
    requested = session.query(Role).filter(Role.id.in_(role_ids)).all()
    if _is_superuser():
        return requested
    allowed_ids = {role.id for role in existing} | {
        role.id for role in current_user.get_all_roles() if role.name != 'admin'
    }
    not_held = sorted(
        (role for role in requested if role.id not in allowed_ids), key=lambda r: r.id
    )
    if not_held:
        refuse_grant(
            'You may only attach roles you hold yourself. Not held: '
            f'{[f"/api2/role/{role.id}" for role in not_held]}.',
            f'Role names: {[role.name for role in not_held]}.',
        )
    return requested


def member_groups_from_uris(
    group_uris: Iterable[str], existing: Iterable
) -> list[Group]:
    '''Resolves group URIs for a user already in the `existing` groups. Each
    other group must be one the caller belongs to, whose roles and ACLs it
    therefore holds. URIs naming no group are skipped.
    '''
    group_ids = _ids_from_uris(group_uris, 'group')
    session = get_db_adapter().session
    requested = session.query(Group).filter(Group.id.in_(group_ids)).all()
    if _is_superuser():
        return requested
    allowed_ids = {group.id for group in existing} | {
        group.id for group in current_user.groups
    }
    not_member = sorted(
        (group for group in requested if group.id not in allowed_ids),
        key=lambda group: group.id,
    )
    if not_member:
        refuse_grant(
            'You may only add users to groups you belong to. Not a member: '
            f'{[f"/api2/group/{group.id}" for group in not_member]}.',
            f'Group names: {[group.name for group in not_member]}.',
        )
    return requested


def verify_acl_grants(
    acls: Iterable[dict], existing_acls: Iterable
) -> list[tuple[ResourceRole, Resource]]:
    '''Resolves a group's or user's ACL list. Each new resource role on a
    resource needs `update_users` on that resource, as sharing it through
    `/api2/resource/<id>/roles` does. Returns the resolved pairs, so the write
    stores exactly what was authorised.
    '''
    existing = {(acl.resource_role_id, acl.resource_id) for acl in existing_acls}
    grants = []
    for acl in acls:
        resource_name = acl['resource'].get('name')
        if not resource_name:
            # An ACL without a resource breaks need building for its holders.
            raise BadRequest(description='Each ACL must name a resource.')
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
            f'{sorted(f"/api2/query_policy/{p.id}" for p in not_held)}.',
            'Policies: '
            f'{sorted((p.dimension, p.dimension_value or "*") for p in not_held)}.',
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
