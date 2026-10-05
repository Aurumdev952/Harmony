# pylint: disable=C0103
from sqlalchemy import func
from werkzeug.exceptions import BadRequest, NotFound

from models.alchemy.permission import Resource, ResourceRole, ResourceType
from web.server.data.data_access import find_one_by_fields, get_db_adapter

_LOOKUP_FAILED = (
    'Errors were encountered while trying to retrieve role and resource data.'
)


def find_by_name(entity_class, name, session=None, name_field='name', **filters):
    '''The `entity_class` row among those matching `filters` whose `name_field`
    equals `name` ignoring case, or None.

    Names compare for equality, never as a LIKE pattern, so `_` and `%` are
    literal. Names are unique only as stored, or not at all for resources, so
    several rows can equal `name` ignoring case: the one spelled exactly `name`
    wins if it is alone, else nobody rather than an arbitrary row.
    '''
    if not name:
        return None
    session = session or get_db_adapter().session
    column = getattr(entity_class, name_field)
    candidates = (
        session.query(entity_class)
        .filter(func.lower(column) == func.lower(name))
        .filter_by(**filters)
        .all()
    )
    if len(candidates) == 1:
        return candidates[0]
    exact = [row for row in candidates if getattr(row, name_field) == name]
    return exact[0] if len(exact) == 1 else None


def _type_mismatch(role, resource):
    # The resource's own name is left out: the caller may not be able to list it.
    return {
        'fields': ['resourceType', 'roleName'],
        'message': (
            f'Role \'{role.name}\' is only valid for resource type: '
            f'\'{role.resource_type.name}\'. The resource is of type '
            f'\'{resource.resource_type.name}\'. '
        ),
    }


def refuse_legacy_role_grant():
    '''The legacy `/api2/{user,group}/<id>/roles` grants built a role
    association from a resource role, with a `resource_id` the association
    lacks, and so never wrote anything but a 500.
    '''
    raise BadRequest(
        description='Roles are not granted here: send roles, and resource roles '
        'as ACLs, with the update of the user or group.'
    )


def refuse_legacy_role_map_grants(role_mapping):
    if any(
        spec.get('sitewideRoles') or spec.get('resources')
        for spec in role_mapping.values()
    ):
        refuse_legacy_role_grant()


def try_get_resource_role(role_name, resource, session=None):
    '''The resource role named `role_name`, for `resource`, which the caller
    already holds and which is never looked up again by its name.

    Raises
    -------
    werkzeug.exceptions.NotFound
        If no resource role has that name, or it is for another resource type.
    '''
    role = find_by_name(ResourceRole, role_name, session)
    if not role:
        error = {
            'fields': ['roleName'],
            'message': f'Role \'{role_name}\' does not exist. ',
        }
    elif role.resource_type_id != resource.resource_type_id:
        error = _type_mismatch(role, resource)
    else:
        return role
    raise NotFound({'errors': [error], 'message': _LOOKUP_FAILED})


def try_get_resource_type(resource_type):
    return find_one_by_fields(
        ResourceType, case_sensitive=True, search_fields={'name': resource_type}
    )


def try_get_role_and_resource(
    role_name, resource_type, resource_name=None, session=None
):
    '''Given a role name, resource type and optionally a resource name, attempts to find the
    corresponding Database entities associated with them.

    Parameters
    ----------
    role_name : string
        The name of the role that you wish to retrieve (e.g. 'dashboard_admin')

    resource_type : string
        The type of resource type that you wish to retrieve (e.g. 'dashboard')

    resource_name (optional): string
        The name of the resource in question (e.g. 'jsc'). If not specified,
        a null value for this entity will be returned.

    Returns
    -------
    tuple
        The first element being the role entity, the second being the resource type entity
        and the third element representing the resource entity (will be null if resource_name
        was not specified).

    Raises
    -------
    werzkeug.exceptions.NotFound
        In the event that one or more of the entities requested could not be found or there is a
        mismatch between resource types for `role` and `resource` (e.g. if `role` is `group_admin`
        and `resource` is `jsc-dashboard`).
    '''
    # NOTE: All references to `role` actually refers to a ResourceRole
    role = find_by_name(ResourceRole, role_name, session)
    resource_type_entity = find_one_by_fields(
        ResourceType,
        case_sensitive=True,
        search_fields={'name': resource_type},
        session=session,
    )
    resource = None
    if resource_name and resource_type_entity:
        resource = find_by_name(
            Resource, resource_name, session, resource_type_id=resource_type_entity.id
        )

    errors = []
    if not role:
        errors.append(
            {
                'fields': ['roleName'],
                'message': f'Role \'{role_name}\' does not exist. ',
            }
        )

    if not resource_type_entity:
        errors.append(
            {
                'fields': ['resourceType'],
                'message': f'Resource type \'{resource_type}\' does not exist. ',
            }
        )

    if resource_name and not resource:
        errors.append(
            {
                'fields': ['resourceName'],
                'message': (
                    'Resource \'%s\' of type \'%s\' does not exist. '
                    % (resource_name, resource_type)
                ),
            }
        )

    if resource and role and resource.resource_type_id != role.resource_type_id:
        errors.append(_type_mismatch(role, resource))

    if errors:
        raise NotFound({'errors': errors, 'message': _LOOKUP_FAILED})

    return (role, resource_type_entity, resource)
