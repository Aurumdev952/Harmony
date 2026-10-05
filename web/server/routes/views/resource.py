from slugify import slugify
from werkzeug.exceptions import NotFound

from models.alchemy.permission import (
    Resource,
    ResourceRole,
    ResourceTypeEnum,
    SitewideResourceAcl,
)
from models.alchemy.security_group import Group, GroupAcl
from models.alchemy.user import UserAcl, UserRoles
from web.server.data.data_access import (
    Transaction,
    find_all_by_fields,
    find_one_by_fields,
    get_db_adapter,
)
from web.server.errors import ItemNotFound
from web.server.routes.views.core import find_by_name
from web.server.routes.views.groups import (
    list_group_roles_for_resource_api,
    update_group_resource_roles,
)
from web.server.routes.views.users import (
    list_user_roles_for_resource_api,
    update_user_resource_roles,
    try_get_user,
)

from web.server.potion.signals import after_roles_update, before_roles_update


def get_resource_by_type_and_name(resource_type, resource_name):
    slugified_name = slugify(resource_name.lower(), separator='_')
    type_member = ResourceTypeEnum.__members__.get(resource_type.upper())
    resources = (
        # pylint: disable=no-member
        Resource.query.filter(
            Resource.name == slugified_name,
            Resource.resource_type_id == type_member.value,
        ).all()
        if type_member
        else []
    )

    # Resource names are not unique: several matches name no one resource.
    if len(resources) == 1:
        return resources[0]

    raise ItemNotFound(resource_type, {'name': resource_name})


def get_sitewide_acl_for_resource_api(resource):
    '''Gets sidewide_acl values for a particular resource.'''
    maybe_sitewide_acl = find_one_by_fields(
        SitewideResourceAcl, True, {'resource_id': resource.id}
    )
    if not maybe_sitewide_acl:
        return {'registeredResourceRole': '', 'unregisteredResourceRole': ''}

    registered_resource_role_name = (
        maybe_sitewide_acl.registered_resource_role.name
        if maybe_sitewide_acl.registered_resource_role
        else ''
    )
    unregistered_resource_role_name = (
        maybe_sitewide_acl.unregistered_resource_role.name
        if maybe_sitewide_acl.unregistered_resource_role
        else ''
    )

    return {
        'registeredResourceRole': registered_resource_role_name,
        'unregisteredResourceRole': unregistered_resource_role_name,
    }


def get_current_resource_roles(resource):
    return {
        'groupRoles': list_group_roles_for_resource_api(resource),
        'sitewideResourceAcl': get_sitewide_acl_for_resource_api(resource),
        'userRoles': list_user_roles_for_resource_api(resource),
    }


def _roles_by_principal(requested, holders, find, remove_missing):
    '''Resolves `requested`, a map from user or group names to the resource
    role names they should hold, to a map from principals to role names, and
    the names that match no principal.

    A name spelled exactly like the name of a principal in `holders` (name to
    principal, for those holding roles on the resource) is that principal;
    other names go to `find`. With `remove_missing`, holders not named get no
    roles.
    '''
    roles_by_principal = {}
    undefined = []
    if requested is None:
        return roles_by_principal, undefined

    for name, roles in requested.items():
        principal = holders.get(name) or find(name)
        if principal is None:
            undefined.append(name)
        else:
            roles_by_principal.setdefault(principal, []).extend(roles)

    if remove_missing:
        for principal in holders.values():
            roles_by_principal.setdefault(principal, [])

    return roles_by_principal, undefined


def _update_sitewide_resource_acl(resource, new_sitewide_resource_acl):
    '''Updates a specific resource's sitewideResourceAcl.'''
    with Transaction() as transaction:
        # Check if there is even an entry here
        sitewide_acl = transaction.find_one_by_fields(
            SitewideResourceAcl, True, {'resource_id': resource.id}
        )
        acl_exists = True
        if not sitewide_acl:
            sitewide_acl = SitewideResourceAcl(resource_id=resource.id)
            acl_exists = False

        registered_resource_role_name = new_sitewide_resource_acl[
            'registeredResourceRole'
        ]
        unregistered_resource_role_name = new_sitewide_resource_acl[
            'unregisteredResourceRole'
        ]

        sitewide_acl.registered_resource_role_id = (
            (
                transaction.find_one_by_fields(
                    ResourceRole, True, {'name': registered_resource_role_name}
                ).id
            )
            if registered_resource_role_name
            else None
        )
        sitewide_acl.unregistered_resource_role_id = (
            (
                transaction.find_one_by_fields(
                    ResourceRole, True, {'name': unregistered_resource_role_name}
                ).id
            )
            if unregistered_resource_role_name
            else None
        )

        if (
            acl_exists
            and not sitewide_acl.registered_resource_role_id
            and not sitewide_acl.unregistered_resource_role_id
        ):
            transaction.delete(sitewide_acl)
            return

        transaction.add_or_update(sitewide_acl, flush=True)


def update_resource_roles(
    resource, user_roles=None, group_roles=None, sitewide_acl=None
):
    # Update sitewide_acl. This can still be independent of other role updates
    _update_sitewide_resource_acl(resource, sitewide_acl)

    session = get_db_adapter().session
    existing_roles = get_current_resource_roles(resource)
    user_acls = find_all_by_fields(UserAcl, {'resource_id': resource.id})
    group_acls = find_all_by_fields(GroupAcl, {'resource_id': resource.id})
    # An empty map of user roles leaves every user's roles alone, while an empty
    # map of group roles removes every group's.
    users, undefined_users = _roles_by_principal(
        user_roles,
        {acl.user.username: acl.user for acl in user_acls},
        lambda username: try_get_user(username, session),
        remove_missing=bool(user_roles),
    )
    groups, undefined_groups = _roles_by_principal(
        group_roles,
        {acl.group.name: acl.group for acl in group_acls},
        lambda name: find_by_name(Group, name, session),
        remove_missing=group_roles is not None,
    )

    # Nothing but the sitewide ACL is written until every name is resolved.
    if undefined_users or undefined_groups:
        errors = [
            {
                'fields': ['username'],
                'message': [f'User with username \'{username}\' cannot be found. '],
            }
            for username in undefined_users
        ]
        errors.extend(
            {
                'fields': ['name'],
                'message': [f'Group with name \'{group_name}\' cannot be found. '],
            }
            for group_name in undefined_groups
        )
        raise NotFound(
            {
                'message': 'Certain user(s) and group(s) could not be found. See the \'errors\' section.',
                'errors': errors,
            }
        )

    for user, role_names in users.items():
        update_user_resource_roles(user, role_names, resource, session, commit=False)
    for group, role_names in groups.items():
        update_group_resource_roles(group, role_names, resource, session)

    new_roles = {
        'userRoles': {user.username: roles for user, roles in users.items()},
        'groupRoles': {group.name: roles for group, roles in groups.items()},
    }
    before_roles_update.send(
        resource, existing_roles=existing_roles, new_roles=new_roles
    )
    session.commit()
    after_roles_update.send(
        resource, existing_roles=existing_roles, new_roles=new_roles
    )
    return (existing_roles, new_roles)


def add_role_user(role, username, session):
    user = try_get_user(username)

    if not user:
        raise ItemNotFound('user', {'username': username})

    role_user = session.find_one_by_fields(
        UserRoles, True, {'role_id': role.id, 'user_id': user.id}
    )
    exists = True

    if not role_user:
        exists = False
        session.add_or_update(UserRoles(role_id=role.id, user_id=user.id))

    return (user, exists)


def update_role_users(role, new_users, session):
    updated_users = []
    role_users = session.find_all_by_fields(UserRoles, {'role_id': role.id})
    for role_user in role_users:
        session.delete(role_user)

    for username in new_users:
        (user, _) = add_role_user(role, username, session)
        updated_users.append(user)
    return updated_users
