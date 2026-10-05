import itertools
from typing import Optional
from logging import LoggerAdapter

from flask import g, request, request_started, session, current_app
from flask_jwt_extended import (
    get_jwt_identity,
    verify_jwt_in_request_optional,
    get_jwt_claims,
    get_raw_jwt,
)
from flask_user import user_logged_in, user_logged_out, current_user, user_registered
from flask_potion.signals import before_create, before_update, before_delete
from flask_principal import (
    Identity,
    AnonymousIdentity,
    UserNeed,
    ItemNeed,
    identity_changed,
    identity_loaded,
)
from jwt import ExpiredSignatureError, InvalidSignatureError
from sqlalchemy import DateTime, or_
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement
from werkzeug.exceptions import BadRequest

from log import LOG
from log.context import current_request_id, new_request_id
from models.alchemy.api_token import APIToken
from models.alchemy.user import User, UserStatusEnum
from models.python.permissions import DimensionFilter, QueryNeed
from web.server.data.data_access import get_db_adapter
from web.server.routes.views.authentication import try_authenticate_user
from web.server.routes.views.authorization import (
    AuthorizedOperation,
    WhitelistedPermission,
)
from web.server.security.permissions import SuperUserPermission
from web.server.security.usernames import find_legacy_token_account
from web.server.util.authentication import USER_ID_CLAIM
from web.server.util.util import get_user_string, get_remote_ip_address

# Dashboard render tokens keep whatever query policy the account they are issued
# for holds.
RENDER_TOKEN_QUERY_NEEDS = ['*']


def register_for_signals(app, principals):
    install_user_events_handlers(app)
    install_identity_loader(principals)
    install_login_manager_signal_handlers(app, app.user_manager.login_manager)
    request_started.connect(initialize_request_logger, app)


# This is the signature of the signal handler.
# pylint:disable=W0613


def initialize_request_logger(app, **kwargs):
    '''Creates an augmented logger that lasts for the lifetime of a flask request. Enables
    additional data to be logged during the request context including username, user id,
    the user's ip address and a unique request-specific ID that can be used to debug all the
    messages associated with a specific request by a user.
    '''

    # The id the request id middleware bound, which the response header also carries.
    request_id = current_request_id() or new_request_id()
    username = ''
    user_id = -1
    ip_address = get_remote_ip_address()

    if current_user.is_authenticated:
        username = current_user.username
        user_id = current_user.id

    log_fields = {
        'username': username,
        'ip_address': ip_address,
        'request_id': request_id,
        'user_id': user_id,
    }

    request_logger = LoggerAdapter(LOG, log_fields)
    g.request_logger = request_logger
    g.request_id = request_id


def _compute_token_item_needs(token_needs):
    all_needs_allowed = '*' in token_needs
    # compute a set of `ItemNeeds` that this token claims to provide
    token_needs = (
        {
            ItemNeed(permission, resource_id, resource_type)
            for permission, resource_id, resource_type in token_needs
        }
        if not all_needs_allowed
        else frozenset()
    )

    # load those needs into identity so we later can test other needs against
    # this identity (if what account provides is allowed by the token)
    token_identity = Identity('jwt')
    token_identity.provides = token_needs

    return (
        # when everything is allowe we just copy everything that account allows
        {need for need in g.identity.provides if not isinstance(need, QueryNeed)}
        if all_needs_allowed
        # otherwise we have a union of what token claims and account allows
        else {
            token_need
            for token_need in token_needs
            if WhitelistedPermission([token_need]).allows(g.identity)
        }
        # and what account claims and token allows
        | {
            provided
            for provided in g.identity.provides
            if WhitelistedPermission([provided]).allows(token_identity)
        }
    )


def _compute_token_query_needs(token_query_needs):
    token_query_needs = (
        [
            QueryNeed(
                {
                    DimensionFilter(
                        dimension_name=dimension,
                        include_values=dfilter.get('include_values', []),
                        exclude_values=dfilter.get('exclude_values', []),
                        all_values=not dfilter.get('include_values', []),
                    )
                    for dimension, dfilter in query_need.items()
                }
            )
            for query_need in token_query_needs
        ]
        if '*' not in token_query_needs
        else [
            QueryNeed(
                {
                    DimensionFilter(
                        dimension_name=dimension,
                        include_values=[],
                        exclude_values=[],
                        all_values=True,
                    )
                }
            )
            for dimension in current_app.zen_config.filters.AUTHORIZABLE_DIMENSIONS
        ]
    )

    if SuperUserPermission().can():
        return set(token_query_needs)

    # Now downgrade those needs that don't fully fall into what account is allowed to do
    acc_query_needs = [aqn for aqn in g.identity.provides if isinstance(aqn, QueryNeed)]
    result = set()
    for token_query_need, acc_query_need in itertools.product(
        token_query_needs, acc_query_needs
    ):
        if token_query_need in result:
            continue

        intersection = token_query_need & acc_query_need
        if intersection:
            result.add(intersection)

    return result


def render_token_query_needs():
    '''The query needs a `query_needs: ['*']` token issued to the current user
    resolves to: the policy a dashboard render made as that user runs under.
    '''
    return _compute_token_query_needs(RENDER_TOKEN_QUERY_NEEDS)


def _compute_token_provides(claims):
    needs = claims.get('needs', [])
    query_needs = claims.get('query_needs', [])
    return _compute_token_item_needs(needs) | _compute_token_query_needs(query_needs)


def _install_token_needs(identity):
    """
    Restrict currently loaded identity with only those needs that are allowed by both
    the identity and the token

    Special need "*" means that token provides everything that the user its issued for is
    capable of. It needs to be specified explicitly to make sure the issuer knows what
    he does.

    Query needs are stored under `query_needs` and are in form of a list of filters:
    [
        {
            dimension1: {'excluded_values': [...]}, - exclude some values, include all others
            dimension2: {'included_values': [...]}, - include some values, exclude all others
            dimension3: {}, - include everything
            ...
        }
    ]
    If neither `included_values` nor `excluded_values` have any elements, it's considered
    that any value is allowed.

    There's also a special dimension name `source` to control what sources are allowed.
    """
    identity.provides = _compute_token_provides(get_jwt_claims())


def on_identity_loaded(sender, identity):
    '''A signal handler that updates the current user's identity with claims
    from the database.
    '''
    # If the user is authenticated and registered in the system,
    # install the default user permissions.
    if not isinstance(identity, AnonymousIdentity):
        # Set the identity user object
        identity.user = current_user
        install_default_user_permissions(identity)

    # NOTE: It will now also cache permissions for anonymous
    # users but before it didn't. Can it cause any harm?
    identity.provides |= current_user.get_permissions()
    if getattr(current_user, 'from_jwt', False):
        _install_token_needs(identity)

    g.request_logger.debug(
        'Identity for User \'%s\' was loaded.',
        get_user_string(current_user),
    )


def install_default_user_permissions(identity):
    '''
    Add permisisons that the current user should be able to perform
    regardless of whatever other roles they possess.
    '''
    identity.provides.add(UserNeed(identity.user.id))

    # TODO - This should not be hardcoded.
    # Always allow the user to view their profile
    identity.provides.add(ItemNeed('view_resource', identity.user.id, 'user'))

    # Continuation of Work for T2148 but now allowing RO-access to all Potion APIs
    identity.provides.add(ItemNeed('view_resource', None, 'user'))
    identity.provides.add(ItemNeed('view_resource', None, 'group'))
    identity.provides.add(ItemNeed('view_resource', None, 'role'))
    identity.provides.add(ItemNeed('view_resource', None, 'resource'))
    identity.provides.add(ItemNeed('view_resource', None, 'configuration'))
    identity.provides.add(ItemNeed('view_resource', None, 'query_policy'))


def install_identity_loader(principals):
    @principals.identity_loader
    def read_identity_from_flask_login():
        if current_user.is_authenticated:
            return Identity(current_user.id)
        return AnonymousIdentity()

    return read_identity_from_flask_login


def install_user_events_handlers(app):
    # These are the signal method signatures
    # pylint:disable=W0612

    @user_registered.connect_via(app)
    def on_user_registered(sender, user):
        g.request_logger.info(
            'Invited user \'%s\' has successfully registered for an account. ',
            get_user_string(user),
        )

    @identity_loaded.connect_via(app)
    def on_user_identity_loaded(sender, identity):
        on_identity_loaded(sender, identity)

    @user_logged_in.connect_via(app)
    def on_user_logged_in(sender, user):
        g.request_logger.info('User \'%s\' logged in', get_user_string(user))
        identity_changed.send(sender, identity=Identity(user.id))

    @user_logged_out.connect_via(app)
    def on_user_logged_out(sender, user):
        if user.is_authenticated:
            g.request_logger.info('User \'%s\' logged out', get_user_string(user))
        identity_changed.send(sender, identity=AnonymousIdentity())
        user.get_permissions.delete_memoized()


def api_token_user_id(token_id: str) -> Optional[int]:
    '''The id of the account an API token was issued to, or None once the
    token is revoked or deleted.'''
    db_session = get_db_adapter().session
    token = db_session.query(APIToken).filter_by(id=token_id).first()
    return token.user_id if token and not token.is_revoked else None


class database_time_from_epoch(FunctionElement):  # pylint: disable=invalid-name
    '''Epoch seconds as a naive timestamp in the time zone `user.created` is
    written in by `current_timestamp()`: the session time zone on Postgres,
    UTC on SQLite. Both sides share a time zone, not a clock: if the server's
    `TimeZone` setting changes, rows written before the change are misread by
    the difference (WP-0k INV-3, T-3).'''

    type = DateTime()
    name = 'database_time_from_epoch'


@compiles(database_time_from_epoch)
def _unsupported_time_from_epoch(element, compiler, **kwargs):
    raise NotImplementedError(f'database_time_from_epoch on {compiler.dialect.name}')


@compiles(database_time_from_epoch, 'postgresql')
def _postgres_time_from_epoch(element, compiler, **kwargs):
    return f'CAST(to_timestamp({compiler.process(element.clauses, **kwargs)}) AS TIMESTAMP)'


@compiles(database_time_from_epoch, 'sqlite')
def _sqlite_time_from_epoch(element, compiler, **kwargs):
    return f"datetime({compiler.process(element.clauses, **kwargs)}, 'unixepoch')"


def account_for_token(username: str, claims: dict, issued_at: Optional[int]):
    '''The active account a JWT was issued to, or None.

    The token names its account by id: an API token through its `api_token`
    row, read on every request so nothing outlives a revoke or a user delete; a
    session or a render token through its `user_id` claim. A token with
    neither, a session issued before WP-0k, gets the one account its username
    can mean. The account must still be active, still have the exact username
    the token names, and not have been created in a later second than the
    token was issued (`iat`), so a token never signs in a later account that
    reuses an id or a username. The database compares the times, in one time
    zone. An account with no `created` (written before the column existed, or
    outside the ORM) is not checked against `iat`.
    '''
    if issued_at is None:
        return None
    if 'id' in claims:
        issued_to = api_token_user_id(claims['id'])
        if issued_to is None:
            return None
    else:
        issued_to = claims.get(USER_ID_CLAIM)
    if issued_to is None:
        legacy = find_legacy_token_account(username)
        if legacy is None:
            return None
        issued_to, username = legacy.id, legacy.username
    return (
        get_db_adapter()
        .session.query(User)
        .filter(
            User.id == issued_to,
            User.username == username,
            User.status_id == UserStatusEnum.ACTIVE.value,
            or_(
                User.created.is_(None),
                User.created < database_time_from_epoch(issued_at + 1),
            ),
        )
        .first()
    )


def install_login_manager_signal_handlers(app, login_manager):
    @login_manager.request_loader
    def login_from_request(request_object=None):
        request_object = request_object or request

        try:
            verify_jwt_in_request_optional()
        except (ExpiredSignatureError, InvalidSignatureError):
            # bypass jwt-extended's error callbacks for now, our own
            # `auth_decorator` will return JSON for API calls and redirects
            # otherwise, and it's not really feasible with the callback.
            # A bad signature (a token signed with a previous JWT_SECRET_KEY, or a
            # forged one) makes the request anonymous, like an expired token.
            pass

        auth_email = get_jwt_identity()
        user = (
            account_for_token(auth_email, get_jwt_claims(), get_raw_jwt().get('iat'))
            if auth_email
            else None
        )
        if user:
            # NOTE: if we found JWT then we don't need the session
            session.permanent = False
            session.modified = False
            user.from_jwt = True
            return user

        try:
            username = request.headers.get('X-Username')
            password = request.headers.get('X-Password')

            if not (username and password):
                # User and password are not provided via login headers
                return None

            LOG.debug('Attempting to authenticate user: \'%s\'.', username)
            user = try_authenticate_user(username, password)

            if user:
                LOG.debug(
                    'User: \'%s\' authenticated successfully.', get_user_string(user)
                )
                return user
            LOG.warning('User: \'%s\' failed to authenticate.', username)
            return None
        except BadRequest:
            return None
        return None


def install_potion_signal_handlers(potion_resource_class):
    '''
    Installs Signal Handlers on Potion's CRUD routes for a given resource class
    to ensure that the user performing the change has the authorization to do so.
    '''

    resource_type = potion_resource_class.meta.name

    # This function is a signal handler. It is not called in this method
    # but this is where we are registering it.
    # pylint:disable=W0612
    @before_create.connect_via(potion_resource_class)
    def before_create_resource(sender, item):
        id_attribute = potion_resource_class.meta.id_attribute
        if resource_type == 'configuration':
            id_attribute = 'id'

        verify_authorization('create_resource', resource_type, item, id_attribute)

    @before_update.connect_via(potion_resource_class)
    def before_update_resource(sender, item, changes):
        id_attribute = potion_resource_class.meta.id_attribute
        if resource_type == 'configuration':
            id_attribute = 'id'

        verify_authorization('edit_resource', resource_type, item, id_attribute)

    @before_delete.connect_via(potion_resource_class)
    def before_delete_resource(sender, item):
        id_attribute = potion_resource_class.meta.id_attribute
        if resource_type == 'configuration':
            id_attribute = 'id'

        verify_authorization('delete_resource', resource_type, item, id_attribute)


def verify_authorization(permission, resource_type, item, id_attribute):
    with AuthorizedOperation(
        permission, resource_type, getattr(item, id_attribute) if item else None
    ):
        return
