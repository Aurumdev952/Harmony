"""
Flask-dependent code is here because pipeline servers don't have flask installed and
flask can't be imported at them
"""

from flask import current_app, has_app_context
from flask_principal import ItemNeed, RoleNeed
from sqlalchemy import event, inspect
from werkzeug.utils import cached_property

from log import LOG
from models.alchemy.permission import SitewideResourceAcl, ResourceTypeEnum
from web.server.data.data_access import Transaction


class BaseWebUserMixin:
    def __caching_id__(self, _obj):
        # flask-caching keys get_permissions by this, or by repr() without it.
        # A username can pass to another account; an id cannot.
        return f'<{self.__class__.__name__} id={self.id}>'

    # NOTE: this hack is necessary because at the moment models
    # are being loaded, we still don't have app context. Is it possible
    # to load them later and thus get rid of it? I'm not sure.
    @cached_property
    def get_permissions(self):
        return current_app.cache.memoize(make_name=lambda name: f'{name}-v2')(
            self._get_permissions
        )

    def _get_permissions(self):
        with Transaction() as transaction:
            # Add specific permission claims to the identity object
            # (e.g.) 'edit_resource' on the 'jsc' dashboard
            return set(
                permission for permission in self.enumerate_permissions(transaction)
            )

    def _build_sitewide_needs(self, transaction, is_registered):
        '''Builds Needs from SitewideResourceAcl, depending if the user is registered or
        not. Yields one Need per permission defined in the ResourceRole.
        '''
        all_sitewide_acls = (
            transaction.find_all_by_fields(SitewideResourceAcl, {}) or []
        )
        for sitewide_acl in all_sitewide_acls:
            resource_role = (
                sitewide_acl.registered_resource_role
                if is_registered
                else sitewide_acl.unregistered_resource_role
            )
            if not resource_role:
                continue
            for need in self._build_acl_needs(
                resource_role.permissions, sitewide_acl.resource
            ):
                yield need

    def _build_acl_needs(self, permissions, resource):
        '''Builds Needs for a particular resource and a list of permissions.'''
        for permission in permissions:
            resource_type = resource.resource_type
            yield ItemNeed(
                permission.permission, resource.id, resource_type.name.name.lower()
            )
            resource_specific_needs = self._maybe_build_alert_needs(
                resource_type, permission, resource
            )

            for need in resource_specific_needs:
                yield need

    @staticmethod
    def _build_role_needs(roles):
        '''Builds Needs for a `Role` object.'''
        # pylint: disable=import-outside-toplevel
        from web.server.routes.views.query_policy import (
            construct_query_need_from_policy,
        )

        for role in roles:
            # Special case specifically for site admin role
            if role.name == 'admin':
                yield RoleNeed(role.name)
                continue

            # Add any query policies associated with the role.
            for query_policy in role.query_policies:
                yield construct_query_need_from_policy(query_policy)

            permissions = role.permissions
            for permission in permissions:
                resource_type = permission.resource_type.name.name.lower()
                yield ItemNeed(permission.permission, None, resource_type)

                # We need to translate 'alert' to 'alert_definitions'
                if resource_type == 'alert':
                    yield ItemNeed(permission.permission, None, 'alert_definitions')

            dashboard_resource_role = role.dashboard_resource_role
            if dashboard_resource_role:
                dashboard_resource_type = ResourceTypeEnum.DASHBOARD.name.lower()
                for permission in dashboard_resource_role.permissions:
                    yield ItemNeed(permission.permission, None, dashboard_resource_type)

            alert_resource_role = role.alert_resource_role
            if alert_resource_role:
                alert_resource_type = ResourceTypeEnum.ALERT.name.lower()
                for permission in alert_resource_role.permissions:
                    yield ItemNeed(permission.permission, None, alert_resource_type)

    @staticmethod
    def _maybe_build_alert_needs(resource_type, permission, resource):
        if resource_type.name == ResourceTypeEnum.ALERT:
            resource_id = resource.id if resource else None
            yield ItemNeed(permission.permission, resource_id, 'alert_definitions')


# The id key keeps accounts apart. Clearing on delete and on insert covers an id
# that is used again, which a restore can do, including rights a request cached
# between the delete's flush and its commit. Clearing on rename is belt and braces.
def _forget_permissions(_mapper, _connection, user):
    # Scripts and some test apps have an app context but no cache.
    if has_app_context() and getattr(current_app, 'cache', None) is not None:
        try:
            user.get_permissions.delete_memoized()
        except Exception:  # pylint: disable=broad-except
            # These run inside the flush: a cache outage must not fail the write.
            # The entry then lasts until its timeout.
            LOG.exception('Could not clear the cached permissions of user %s', user.id)


def _forget_permissions_on_rename(mapper, connection, user):
    if inspect(user).attrs.username.history.has_changes():
        _forget_permissions(mapper, connection, user)


event.listen(BaseWebUserMixin, 'after_delete', _forget_permissions, propagate=True)
event.listen(BaseWebUserMixin, 'after_insert', _forget_permissions, propagate=True)
event.listen(
    BaseWebUserMixin, 'after_update', _forget_permissions_on_rename, propagate=True
)
