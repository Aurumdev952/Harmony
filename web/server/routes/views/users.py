from collections import defaultdict, namedtuple
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING, TypedDict

from flask import g, current_app
from flask_user import current_user
from sqlalchemy.dialects.postgresql import insert

from models.alchemy.api_token import APIToken
from models.alchemy.alerts import AlertDefinition
from models.alchemy.dashboard import Dashboard
from models.alchemy.security_group import Group
from models.alchemy.permission import Resource, ResourceRole, Role
from models.alchemy.user import User, UserAcl, UserStatusEnum
from web.server.data.data_access import (
    get_db_adapter,
    add_entity,
    delete_entity,
    find_one_by_fields,
    find_all_by_fields,
    Transaction,
)
from web.server.errors import UserAlreadyInvited
from web.server.routes.views.core import (
    find_by_name,
    refuse_legacy_role_map_grants,
    try_get_resource_role,
    try_get_role_and_resource,
)
from web.server.routes.views.invite import send_invite_emails
from web.server.util.util import get_user_string, Success
from web.server.potion.signals import after_user_role_change, before_user_role_change

if TYPE_CHECKING:
    from sqlalchemy.orm.session import Session

UNREGISTERED_USER_USERNAME = 'anonymous_user_tracking@zenysis.com'
UNREGISTERED_USER_FIRST = 'Anonymous'
UNREGISTERED_USER_LAST = 'User'

SUCCESS_USER_ROLE_ADDED = 'USER_ROLE_ADDED'
SUCCESS_USER_ROLE_DELETED = 'USER_ROLE_DELETED'

Invitee = namedtuple('Invitee', ['name', 'email'])


class RollResourceType(TypedDict):
    sitewideRoles: List[str]
    resources: Dict[str, List[str]]


class ResourceType(TypedDict):
    label: str
    name: str
    resourceType: str


class ResourceRoleType(TypedDict):
    name: str
    resourceType: str


class AclType(TypedDict):
    resource: ResourceType
    resourceRole: ResourceRoleType


class UserObject(TypedDict):
    username: str
    first_name: str
    last_name: str
    phone_number: str
    status_id: str
    acls: List[AclType]
    roles: List[str]
    groups: List[str]


APITokenType = TypedDict('APITokenType', {'$uri': str, 'is_revoked': bool, 'id': str})


def try_get_user(username: str, session: 'Optional[Session]' = None) -> Optional[User]:
    return find_by_name(User, username, session, name_field='username')


def try_get_user_acl(
    user_id: int,
    resource_role_id: int,
    resource_id: Optional[int] = None,
    session: 'Optional[Session]' = None,
) -> Optional[UserAcl]:
    '''Attempt to find a user role association for a given user, resource_role
    and resource.
    '''
    return find_one_by_fields(
        UserAcl,
        case_sensitive=True,
        search_fields={
            'user_id': user_id,
            'resource_role_id': resource_role_id,
            'resource_id': resource_id,
        },
        session=session,
    )


def list_roles_for_resource(
    user: User, resource: Resource, session: 'Optional[Session]' = None
) -> List[UserAcl]:
    '''Returns an enumeration of `UserAcl` instances matching the given user and resource.'''
    return find_all_by_fields(
        UserAcl,
        search_fields={'user_id': user.id, 'resource_id': resource.id},
        session=session,
    )


def list_user_roles_for_resource_api(
    resource: Resource, session: 'Optional[Session]' = None
) -> Dict[str, List[str]]:
    '''Returns an enumeration of the users and the roles that they hold (if any) for a given
    resource. Users that do not hold any roles specific to the resource will not
    be listed.
    '''
    matching_acls = find_all_by_fields(
        UserAcl, search_fields={'resource_id': resource.id}, session=session
    )
    username_to_role_list = defaultdict(lambda: [])
    for acl in matching_acls:
        username_to_role_list[acl.user.username].append(acl.resource_role.name)

    return username_to_role_list


def force_delete_user(
    user: User,
    session: 'Optional[Session]' = None,
    flush: bool = True,
    commit: bool = True,
) -> None:
    '''Force deletes a user by deleting all of the alerts and dashboards
    associated with them along with the user entity.
    '''

    session = session or get_db_adapter().session

    # NOTE: type suppression is necessary here because SQL Alchemy model attributes
    # do not contain __iter__ attributes so mypy will complain that `roles` is not iterable
    for dashboard in user.dashboards:  # type: ignore
        delete_entity(session, dashboard)

    alerts = find_all_by_fields(
        AlertDefinition, search_fields={'user_id': user.id}, session=session
    )
    for alert in alerts:
        delete_entity(session, alert, commit=True)

    session.delete(user)

    if flush:
        session.flush()

    if commit:
        session.commit()


def add_user_acl(
    user: User,
    resource_role_name: str,
    resource: Resource,
    session: 'Optional[Session]' = None,
    flush: bool = True,
    commit: bool = True,
) -> Tuple[UserAcl, bool]:
    '''Gives `user` the resource role `resource_role_name` on `resource`, the
    row the caller holds, never one found again by its name.
    '''
    session = session or get_db_adapter().session
    resource_role = try_get_resource_role(resource_role_name, resource, session)
    entity = try_get_user_acl(user.id, resource_role.id, resource.id, session)
    exists = False

    if not entity:
        exists = True
        entity = UserAcl(
            user_id=user.id, resource_role_id=resource_role.id, resource_id=resource.id
        )
        before_user_role_change.send(user, role=resource_role)
        add_entity(session, entity, flush, commit)
        after_user_role_change.send(user, role=resource_role)

    return (entity, exists)


def delete_user_role(
    user: User,
    role_name: str,
    resource_type: str,
    resource_name: Optional[str],
    session: 'Optional[Session]' = None,
    flush: bool = True,
    commit: bool = True,
) -> Tuple[Optional[UserAcl], bool]:
    session = session or get_db_adapter().session
    (role, resource_type, resource) = try_get_role_and_resource(
        role_name, resource_type, resource_name, session
    )
    resource_id = resource.id if resource else None
    entity = try_get_user_acl(user.id, role.id, resource_id)
    exists = False

    if entity:
        exists = True
        before_user_role_change.send(user, role=role)
        delete_entity(session, entity, flush, commit)
        after_user_role_change.send(user, role=role)

    return (entity, exists)


def update_user_roles_from_map(
    user: User,
    role_mapping: Dict[str, RollResourceType],
    session: 'Optional[Session]' = None,
    flush: bool = True,
    commit: bool = True,
) -> None:
    '''Removes every role of `user`. A map naming any role is refused.'''
    refuse_legacy_role_map_grants(role_mapping)
    session = session or get_db_adapter().session

    # NOTE: type suppression is necessary here because SQL Alchemy model attributes
    # do not contain __iter__ attributes so mypy will complain that `roles` is not iterable
    for role in list(user.roles):  # type: ignore
        before_user_role_change.send(user, role=role)
        user.roles.remove(role)  # type: ignore[attr-defined]
        after_user_role_change.send(user, role=role)

    if flush:
        session.flush()

    if commit:
        session.commit()


def list_resource_roles_for_user(user_id: int) -> List[UserAcl]:
    return find_all_by_fields(UserAcl, search_fields={'user_id': user_id})


def list_resource_roles_for_user_and_resource(
    resource_id: int, user_id: int
) -> List[UserAcl]:
    return find_all_by_fields(
        UserAcl, search_fields={'resource_id': resource_id, 'user_id': user_id}
    )


def update_user_resource_roles(
    user: User,
    role_names: List[str],
    resource: Resource,
    session: 'Optional[Session]' = None,
    flush: bool = True,
    commit: bool = True,
) -> List[UserAcl]:
    '''Replaces the resource roles `user` holds on `resource` with `role_names`.'''
    session = session or get_db_adapter().session
    for acl in list_resource_roles_for_user_and_resource(resource.id, user.id):
        session.delete(acl)

    # Flushed and committed once below, so the update is one transaction.
    new_role_entities = [
        add_user_acl(user, role_name, resource, session, flush=False, commit=False)[0]
        for role_name in role_names
    ]

    if flush:
        session.flush()

    if commit:
        session.commit()

    return new_role_entities


def replace_user_acls(user: User, grants: List[Tuple[ResourceRole, Resource]]) -> None:
    '''Replaces the user's ACLs with `grants`, `(resource_role, resource)` pairs
    already resolved and authorised by `verify_acl_grants`.
    '''
    session = get_db_adapter().session
    for acl in list_resource_roles_for_user(user.id):
        session.delete(acl)
    for resource_role_id, resource_id in {
        (resource_role.id, resource.id) for resource_role, resource in grants
    }:
        session.add(
            UserAcl(
                user_id=user.id,
                resource_role_id=resource_role_id,
                resource_id=resource_id,
            )
        )
    session.commit()


def update_user_groups(user: User, groups: List[Group]) -> None:
    with Transaction():
        # TODO: fix type error
        user.groups = groups  # type: ignore


def issue_api_token(user: User) -> APIToken:
    '''Generates an API token for `user` and stores it, so the token authenticates as
    soon as the caller has it.'''
    token = APIToken.generate_token(user)
    # generate_token sets the user through a view-only relationship, which is not saved.
    token.user_id = user.id
    with Transaction() as transaction:
        transaction.add_or_update(token)
    return token


def update_user_api_tokens(user: User, tokens: List[APITokenType]):
    # pylint: disable=import-outside-toplevel
    from web.server.security.signal_handlers import check_token_validity

    if not tokens:
        # nothing to do here
        return

    to_revoke = [
        token['$uri'].rsplit('/', 1)[-1] for token in tokens if token['is_revoked']
    ]
    with Transaction() as transaction:
        # create all the tokens that still are not there
        transaction.run_raw().execute(
            insert(APIToken)
            .values(
                [
                    {
                        'id': token['id'],
                        'user_id': user.id,
                    }
                    for token in tokens
                ]
            )
            .on_conflict_do_nothing()
        )

        # now revoke tokens to be revoked, we don't allow un-revoke them
        user.api_tokens.filter(  # type: ignore[attr-defined]
            APIToken.is_revoked.is_(False),
            APIToken.id.in_(to_revoke),
        ).update({'is_revoked': True}, synchronize_session=False)

        # invalidate validity caches because the state of the tokens has changed
        memoized = current_app.cache.memoize()(check_token_validity)
        for token in tokens:
            current_app.cache.delete_memoized(memoized, token['id'])


def build_user_updates(user_obj: UserObject, roles: List[Role]) -> Dict[str, Any]:
    '''Gather necessary components that need to be updated in a user. `roles`
    are already resolved and authorised.
    '''
    user_updates = {
        'username': user_obj['username'],
        'first_name': user_obj['first_name'],
        'last_name': user_obj['last_name'],
        'phone_number': user_obj['phone_number'],
        'status_id': user_obj['status_id'],
        'roles': roles,
    }

    # NOTE: This is the only action and attribute that a non-admin can
    # affect. Corner case where a user is invited by an admin and activates
    # their account, and without refreshing the page, the admin assigns
    # something to the user and status gets overwritten. Since a status cannot
    # revert back to pending, we'll remove this from the updates
    if user_obj['status_id'] == UserStatusEnum.PENDING.value:
        user_updates.pop('status_id')
    return user_updates


def delete_user_role_api(
    user: User,
    role_name: str,
    resource_type: str,
    resource_name: Optional[str] = None,
    session: 'Optional[Session]' = None,
    flush: bool = True,
    commit: bool = True,
) -> Success:
    '''Delete a user role association for a given user, role and resource.'''
    delete_user_role(
        user, role_name, resource_type, resource_name, session, flush, commit
    )

    resource_string = (
        f'Resource \'{resource_name}\' of type \'{resource_type}\''
        if resource_name
        else f'all resources of type \'{resource_type}\''
    )
    message = '%s Role \'%s\' on %s for User \'%s\'' % (
        'Revoked' if commit else 'Commit pending for revocation of',
        role_name,
        resource_string,
        get_user_string(user),
    )

    g.request_logger.info(message)
    return Success({'code': SUCCESS_USER_ROLE_DELETED, 'message': message})


def invite_users(invitees: List[Invitee]) -> List[User]:
    with Transaction() as transaction:
        # First make sure that all invitees are not already registered users
        emails = [user.email.lower() for user in invitees]
        pending_users = []
        # pylint:disable=E1101
        existing_users = User.query.filter(
            User.username.in_(emails), User.status_id != UserStatusEnum.PENDING.value
        ).all()
        # pylint:disable=E1101
        existing_pending_users = User.query.filter(
            User.username.in_(emails), User.status_id == UserStatusEnum.PENDING.value
        ).all()

        existing_username_to_user = {}
        for user in existing_pending_users:
            existing_username_to_user[user.username.lower()] = user

        if existing_users != []:
            # ERROR: some users have already registered
            existing_emails = [user.username for user in existing_users]
            raise UserAlreadyInvited(existing_emails)

        # Add all invitees to the database as Pending Users
        for invitee in invitees:
            email = invitee.email.lower()
            existing_user = existing_username_to_user.get(email)
            if not existing_user:
                pending_user = User(
                    username=email,
                    first_name=invitee.name,
                    last_name='',
                    status_id=UserStatusEnum.PENDING.value,
                )
                pending_users.append(
                    transaction.add_or_update(pending_user, flush=True)
                )
            else:
                pending_users.append(existing_user)

        # Now send emails to all of them
        send_invite_emails(pending_users)

    return pending_users


def get_anonymous_user() -> User:
    '''Fetch anonymous user. Create if it doesn't already exist.'''
    with Transaction() as transaction:
        maybe_anon_user = transaction.find_one_by_fields(
            User, False, {'username': UNREGISTERED_USER_USERNAME}
        )
        if maybe_anon_user:
            return maybe_anon_user

        # NOTE: Only to be used for placeholder user objects that track
        # unregistered user activity
        return transaction.add_or_update(
            User(
                username=UNREGISTERED_USER_USERNAME,
                first_name=UNREGISTERED_USER_FIRST,
                last_name=UNREGISTERED_USER_LAST,
                status_id=UserStatusEnum.ACTIVE.value,
            ),
            flush=True,
        )


def get_current_user() -> User:
    '''Safely fetches the current user object, taking into account unregistered
    users. Use this instead of flask_user.current_user if ever code path is used
    with unregistered users.
    '''
    return get_anonymous_user() if current_user.is_anonymous else current_user


def get_user_owned_resources(user: User) -> List[Resource]:
    '''Get the resources owned by a given user.'''
    with Transaction() as transaction:
        user_id = user.id
        owned_dashboards = transaction.find_all_by_fields(
            Dashboard, {'author_id': user_id}
        )
        owned_alerts = transaction.find_all_by_fields(
            AlertDefinition, {'user_id': user_id}
        )
        resource_ids = [dashboard.resource_id for dashboard in owned_dashboards] + [
            alert.authorization_resource_id for alert in owned_alerts
        ]
        return (
            transaction.run_raw()
            .query(Resource)
            .filter(Resource.id.in_(resource_ids))
            .all()
        )
