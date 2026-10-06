from collections import defaultdict

from models.alchemy.security_group import GroupAcl, GroupRoles, GroupUsers
from web.server.data.data_access import (
    get_db_adapter,
    add_entity,
    delete_entity,
    find_one_by_fields,
    find_all_by_fields,
    Transaction,
)
from web.server.errors import ItemNotFound
from web.server.potion.signals import after_user_group_change
from web.server.routes.views.users import try_get_user
from web.server.routes.views.core import (
    find_named_resource,
    try_get_resource_role,
    try_get_role_and_resource,
)


def try_get_group_acl(group_id, resource_role_id, resource_id):
    return find_one_by_fields(
        GroupAcl,
        case_sensitive=True,
        search_fields={
            'group_id': group_id,
            'resource_role_id': resource_role_id,
            'resource_id': resource_id,
        },
    )


def try_get_group_user(group_id, user_id):
    return find_one_by_fields(
        GroupUsers,
        case_sensitive=True,
        search_fields={'group_id': group_id, 'user_id': user_id},
    )


def list_roles_for_resource(group, resource):
    return find_all_by_fields(
        GroupAcl, search_fields={'group_id': group.id, 'resource_id': resource.id}
    )


def list_resource_roles_for_group(group_id):
    return find_all_by_fields(GroupAcl, search_fields={'group_id': group_id})


def list_resource_roles_for_group_and_resource(group_id, resource_id):
    return find_all_by_fields(
        GroupAcl, search_fields={'group_id': group_id, 'resource_id': resource_id}
    )


def list_group_users(group):
    return find_all_by_fields(GroupUsers, search_fields={'group_id': group.id})


def list_group_roles_for_resource_api(resource):
    '''Returns an enumeration of groups and the roles that they hold for a given
    resource. Groups that do not hold any roles specific to the resource will not
    be listed.
    '''
    matching_acls = find_all_by_fields(
        GroupAcl, search_fields={'resource_id': resource.id}
    )
    username_to_role_list = defaultdict(lambda: [])
    for acl in matching_acls:
        username_to_role_list[acl.group.name].append(acl.resource_role.name)

    return username_to_role_list


def add_group_role(
    group,
    role_name,
    resource_type,
    resource_name,
    session=None,
    flush=True,
    commit=True,
):
    session = session or get_db_adapter().session
    (role, resource_type, resource) = try_get_role_and_resource(
        role_name, resource_type, resource_name
    )
    resource_id = resource.id if resource else None
    entity = try_get_group_acl(group.id, role.id, resource_id)
    exists = True

    if not entity:
        exists = False
        entity = GroupRoles(group_id=group.id, role_id=role.id, resource_id=resource_id)
        add_entity(session, entity, flush, commit)

    return (entity, exists)


def add_group_acl(
    group,
    resource_role_name,
    resource,
    session=None,
    flush=True,
    commit=True,
):
    '''Gives `group` the resource role `resource_role_name` on `resource`, the
    row the caller holds, never one found again by its name.
    '''
    session = session or get_db_adapter().session
    resource_role = try_get_resource_role(resource_role_name, resource, session)
    entity = try_get_group_acl(group.id, resource_role.id, resource.id)
    exists = True

    if not entity:
        exists = False
        entity = GroupAcl(
            group_id=group.id,
            resource_role_id=resource_role.id,
            resource_id=resource.id,
        )
        add_entity(session, entity, flush, commit)

    return (entity, exists)


def delete_group_role(
    group,
    role_name,
    resource_type,
    resource_name,
    session=None,
    flush=True,
    commit=True,
):
    session = session or get_db_adapter().session
    (role, resource_type, resource) = try_get_role_and_resource(
        role_name, resource_type, resource_name
    )
    resource_id = resource.id if resource else None
    entity = try_get_group_acl(group.id, role.id, resource_id)
    exists = False

    if entity:
        exists = True
        delete_entity(session, entity, flush, commit)
    return (entity, exists)


def update_group_resource_roles(
    group, new_resource_roles, resource=None, session=None, flush=True, commit=True
):
    session = session or get_db_adapter().session
    new_role_entities = []
    # List only resource roles acls for group and resource ids when resource
    # exists.
    if resource:
        resource_roles = list_resource_roles_for_group_and_resource(
            group.id, resource.id
        )
    else:
        resource_roles = list_resource_roles_for_group(group.id)

    # TODO: Refactor this to take advantage of SQLAlchemy rather than
    # manually deleting and re-adding resource roles
    for resource_role in resource_roles:
        session.delete(resource_role)

    for resource_role in new_resource_roles:
        role_name = resource_role['role_name']
        # Without `resource`, each role names its resource.
        target = resource or find_named_resource(resource_role, session)

        # Do not flush or commit these changes. We want to perform the update in a transacted
        # fashion.
        (result, _) = add_group_acl(
            group, role_name, target, session, flush=False, commit=False
        )
        new_role_entities.append(result)

    if flush:
        session.flush()

    if commit:
        session.commit()

    for group_user in group.users.all():
        after_user_group_change.send(group_user, group=group)

    return new_role_entities


def update_group_roles_from_map(
    group, role_mapping, session=None, flush=True, commit=True
):
    session = session or get_db_adapter().session
    new_role_entities = []
    group.roles = []

    for resource_type in list(role_mapping.keys()):
        resource_to_roles = role_mapping[resource_type]['resources']
        sitewide_roles = role_mapping[resource_type]['sitewideRoles']

        # Add all sitewide roles for the current resource type
        for role_name in sitewide_roles:
            (result, _) = add_group_role(
                group,
                role_name,
                resource_type,
                None,
                session,
                flush=False,
                commit=False,
            )
            new_role_entities.append(result)

        # Add all resource specific roles for the current resource type
        for resource_name, role_names in list(resource_to_roles.items()):
            for role_name in role_names:
                (result, _) = add_group_role(
                    group,
                    role_name,
                    resource_type,
                    resource_name,
                    session,
                    flush=False,
                    commit=False,
                )
                new_role_entities.append(result)

    if flush:
        session.flush()

    if commit:
        session.commit()

    return new_role_entities


def add_group_user(group, username, session=None, flush=True, commit=True):
    session = session or get_db_adapter().session
    user = try_get_user(username)

    if not user:
        raise ItemNotFound('user', {'username': username})

    entity = try_get_group_user(group.id, user.id)
    exists = True

    if not entity:
        exists = False
        entity = GroupUsers(group_id=group.id, user_id=user.id)
        add_entity(session, entity, flush, commit)

    return (user, exists)


def delete_group_user(group, username, session=None, flush=True, commit=True):
    session = session or get_db_adapter().session
    user = try_get_user(username)

    if not user:
        raise ItemNotFound('user', {'username': username})

    entity = try_get_group_user(group.id, user.id)
    exists = False

    if entity:
        exists = True
        delete_entity(session, entity, flush, commit)

    return (user, exists)


def update_group_users(group, new_users, session=None, flush=True, commit=True):
    session = session or get_db_adapter().session
    updated_users = []
    group_user_relations = list_group_users(group)

    for group_user in group_user_relations:
        session.delete(group_user)
        updated_users.append(group_user.user)

    for username in new_users:
        # Do not flush or commit these changes. We want to perform the update in a transacted
        # fashion.
        (result, _) = add_group_user(
            group, username, session, flush=False, commit=False
        )
        updated_users.append(result)

    if flush:
        session.flush()

    if commit:
        session.commit()

    for group_user in updated_users:
        after_user_group_change.send(group_user, group=group)

    return updated_users


def replace_group_acls(group, grants):
    '''Replaces the group's ACLs with `grants`, `(resource_role, resource)` pairs
    already resolved and authorised by `verify_acl_grants`.
    '''
    session = get_db_adapter().session
    for acl in list_resource_roles_for_group(group.id):
        session.delete(acl)
    for resource_role_id, resource_id in {
        (resource_role.id, resource.id) for resource_role, resource in grants
    }:
        session.add(
            GroupAcl(
                group_id=group.id,
                resource_role_id=resource_role_id,
                resource_id=resource_id,
            )
        )
    session.commit()

    for group_user in group.users.all():
        after_user_group_change.send(group_user, group=group)


def delete_group(group):
    with Transaction() as transaction:
        group_users = transaction.find_all_by_fields(GroupUsers, {'group_id': group.id})
        for group_user in group_users:
            transaction.delete(group_user)
            after_user_group_change.send(group_user.user, group=group)
        transaction.delete(group)
