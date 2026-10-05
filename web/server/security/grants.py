'''What a caller may give a group, a user or a role.

Holding `edit_resource` on a group, a user or a role lets a caller change it,
not decide what it receives. A non-superuser may attach or confer only grants
it already holds: roles, membership of its own groups, query policies and
data export. Permissions and resource roles on a role pass the
`update_permissions` gate, and a resource role on a resource needs
`update_users` there. Roles, groups and ACLs the target group or user already
has may be sent again unchanged.

A username change or a password reset is not a grant, but it can hand the
caller the user's account: the reset link goes to the username. A non-superuser
may do either only to a user whose grants are among its own.

"Superuser" is the identity (`current_user_is_superuser`), never the account,
so a token narrowed on an admin account grants like a non-superuser. What a
non-superuser holds comes from its account.
'''

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, NoReturn

from flask import g
from flask_login import current_user
from flask_principal import ItemNeed, Need
from werkzeug.exceptions import BadRequest, Forbidden

from models.alchemy.permission import Resource, ResourceRole, Role
from models.alchemy.security_group import Group, GroupAcl
from models.alchemy.user import User, UserAcl
from models.alchemy.user.web_base_user import BaseWebUserMixin
from web.server.data.data_access import get_db_adapter
from web.server.potion.access import get_id_from_uri
from web.server.routes.views.authorization import (
    current_user_is_superuser,
    is_authorized,
)
from web.server.routes.views.core import try_get_role_and_resource
from web.server.routes.views.query_policy import construct_query_need_from_policy
from web.server.security.permissions import SUPERUSER_ROLENAME
from web.server.util.util import get_user_string

if TYPE_CHECKING:
    from web.server.routes.views.permission import RoleFields


def refuse_grant(description: str, detail: str) -> NoReturn:
    _refuse('grant', description, detail)


def _refuse(action: str, description: str, detail: str) -> NoReturn:
    '''The 403 body is `description` alone. `detail`, which names what was
    refused, goes only to the audit line: naming a role, group or policy would
    tell the caller that an id it cannot list exists.
    '''
    # The log formatter drops LoggerAdapter extras, so the caller goes in the text.
    g.request_logger.warning(
        'Refused %s by \'%s\': %s %s',
        action,
        get_user_string(current_user),
        description,
        detail,
    )
    raise Forbidden(description=description)


def _account_needs() -> set[Need]:
    '''Needs are compared by equality, never by `QueryNeed` containment, which
    does not follow how policies combine into the Druid filter: a broader held
    policy is not trusted to cover a narrower one.
    '''
    return current_user.get_permissions()


def _exports_data() -> bool:
    return any(role.enable_data_export for role in current_user.get_all_roles())


def _ids_from_uris(uris: Iterable[str], kind: str) -> set[int]:
    try:
        return {get_id_from_uri(uri) for uri in uris}
    except (AttributeError, TypeError, ValueError) as error:
        raise BadRequest(description=f'Expected a list of {kind} URIs.') from error


def held_roles_from_uris(
    role_uris: Iterable[str], existing: Iterable[Role] = ()
) -> list[Role]:
    '''Resolves role URIs. A non-superuser is refused any role it does not hold
    unless the target already has it (`existing`). URIs naming no role are
    skipped.
    '''
    role_ids = _ids_from_uris(role_uris, 'role')
    requested = get_db_adapter().session.query(Role).filter(Role.id.in_(role_ids))
    roles = sorted(requested, key=lambda role: role.id)
    if current_user_is_superuser():
        return roles
    allowed_ids = {role.id for role in existing} | {
        role.id
        for role in current_user.get_all_roles()
        # An admin account whose identity is not a superuser (a narrowed token)
        # must not pass the admin role on.
        if role.name != SUPERUSER_ROLENAME
    }
    not_held = [role for role in roles if role.id not in allowed_ids]
    if not_held:
        refuse_grant(
            'You may only attach roles you hold yourself.',
            f'Not held: {[(role.id, role.name) for role in not_held]}.',
        )
    return roles


def member_groups_from_uris(
    group_uris: Iterable[str], existing: Iterable[Group]
) -> list[Group]:
    '''Resolves group URIs for a user. A non-superuser is refused any group it
    does not belong to, and so whose roles and ACLs it does not hold, unless
    the user is already in it (`existing`). URIs naming no group are skipped.
    '''
    group_ids = _ids_from_uris(group_uris, 'group')
    requested = get_db_adapter().session.query(Group).filter(Group.id.in_(group_ids))
    groups = sorted(requested, key=lambda group: group.id)
    if current_user_is_superuser():
        return groups
    allowed_ids = {group.id for group in existing} | {
        group.id
        for group in current_user.groups
        # As in `held_roles_from_uris`: a narrowed token on an admin account
        # must not pass on a group carrying the admin role.
        if all(role.name != SUPERUSER_ROLENAME for role in group.roles)
    }
    not_member = [group for group in groups if group.id not in allowed_ids]
    if not_member:
        refuse_grant(
            'You may only add users to groups you belong to.',
            f'Not a member: {[(group.id, group.name) for group in not_member]}.',
        )
    return groups


def verify_acl_grants(
    acls: Iterable[Mapping[str, Any]],
    existing_acls: Iterable[GroupAcl | UserAcl],
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
                f'\'{resource.name}\' needs the \'update_users\' permission on it.',
                '',
            )
    return grants


def verify_role_grants(new_role: RoleFields, role: Role | None = None) -> None:
    '''Checks a role create (`role` is None) or update. Every holder of the role,
    the caller included, gains what is added.

    A non-superuser reaches only roles it holds (`RoleResourceManager`), so the
    role's own policies and export are among its account's: resending them
    passes the checks below without an exemption.
    '''
    if role is None:
        permission_ids, dashboard_role_id, alert_role_id = set(), None, None
    else:
        # sqlmypy types an untyped `relationship` as one `Permission`.
        permission_ids = {
            permission.id
            for permission in role.permissions  # type: ignore[attr-defined]
        }
        dashboard_role_id = role.dashboard_resource_role_id
        alert_role_id = role.alert_resource_role_id
    gated = [
        name
        for name, changed in (
            (
                'permissions',
                {permission.id for permission in new_role['permissions']}
                != permission_ids,
            ),
            (
                'dashboard resource role',
                new_role['dashboard_resource_role_id'] != dashboard_role_id,
            ),
            (
                'alert resource role',
                new_role['alert_resource_role_id'] != alert_role_id,
            ),
        )
        if changed
    ]
    if gated and not is_authorized(
        'update_permissions', 'role', role.id if role else None
    ):
        refuse_grant(
            f'Changing the {", ".join(gated)} of a role needs the '
            '\'update_permissions\' permission.',
            '',
        )

    if current_user_is_superuser():
        return
    account_needs = _account_needs()
    not_held = [
        policy
        for policy in new_role['query_policies']
        if construct_query_need_from_policy(policy) not in account_needs
    ]
    if not_held:
        refuse_grant(
            'You may only add query policies you hold yourself.',
            'Not held: '
            f'{[(p.id, p.dimension, p.dimension_value or "*") for p in not_held]}.',
        )
    if new_role['enable_data_export'] and not _exports_data():
        refuse_grant(
            'You may only allow data export if you can export data yourself.', ''
        )


def holds_everything_in(role: Role) -> bool:
    '''Whether the caller's account already holds every need `role` grants. Its
    policies passed `verify_role_grants`, so only permissions and resource roles
    can be missing.
    '''
    account_needs = _account_needs()
    # pylint: disable=protected-access
    return all(
        need in account_needs for need in BaseWebUserMixin._build_role_needs([role])
    )


def verify_may_rename(user: User) -> None:
    _verify_holds_all_grants_of(
        user,
        'username change',
        'You may only change the username of users whose access you hold yourself.',
    )


def verify_may_reset_password(user: User) -> None:
    _verify_holds_all_grants_of(
        user,
        'password reset',
        'You may only reset the password of users whose access you hold yourself.',
    )


def _verify_holds_all_grants_of(user: User, action: str, description: str) -> None:
    '''Refuses a non-superuser unless it holds every grant of `user`: each
    role, direct or through a group (so the admin role by any path, and each
    role's query policies and data export), each group membership, and what
    each of the user's ACLs allows.
    '''
    if current_user_is_superuser():
        return
    held_role_ids = {
        role.id
        for role in current_user.get_all_roles()
        if role.name != SUPERUSER_ROLENAME
    }
    member_group_ids = {group.id for group in current_user.groups}
    account_needs = _account_needs()
    roles = sorted(
        {
            (role.id, role.name)
            for role in user.get_all_roles()
            if role.id not in held_role_ids
        }
    )
    # sqlmypy types an untyped `relationship` as one object.
    groups = [
        (group.id, group.name)
        for group in user.groups  # type: ignore[attr-defined]
        if group.id not in member_group_ids
    ]
    acls = [
        (acl.resource_role.name, acl.resource_id)
        for acl in user.acls  # type: ignore[attr-defined]
        if not _holds_acl(user, acl, account_needs)
    ]
    if roles or groups or acls:
        _refuse(
            action,
            description,
            f'User {user.id} holds roles {roles}, groups {groups}, ACLs {acls}.',
        )


def _holds_acl(user: User, acl: UserAcl, account_needs: set[Need]) -> bool:
    '''Whether the caller's account holds what `acl` allows, on that resource
    or on every resource of its type.
    '''
    # `User` gains the web mixin at import time, out of mypy's sight.
    needs = user._build_acl_needs(  # type: ignore[attr-defined]
        acl.resource_role.permissions, acl.resource
    )
    return all(
        need in account_needs or ItemNeed(need.method, None, need.type) in account_needs
        for need in needs
    )
