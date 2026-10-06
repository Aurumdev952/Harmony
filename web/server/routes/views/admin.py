# mypy: disallow_untyped_defs=True
from logging import Logger, LoggerAdapter
from typing import Union

from flask import current_app, g
from flask_user import current_user
from flask_user.signals import user_forgot_password
from werkzeug.exceptions import BadGateway

from log import LOG
from models.alchemy.user import User, UserStatusEnum
from web.server.errors import ItemNotFound, NotificationError
from web.server.data.data_access import Transaction
from web.server.security.usernames import find_user_by_username, username_taken
from web.server.util.deployment_links import deployment_url


def may_set_password_from_reset(user: User) -> bool:
    '''Whether a valid reset token lets `user` set a password: an active
    account, or a pending one (an invitee an admin sent a reset link: its
    first password) with no registered account equal to it ignoring case. A
    deactivated account may not set a password and sign in again.'''
    if user.status_id == UserStatusEnum.ACTIVE.value:
        return True
    return user.status_id == UserStatusEnum.PENDING.value and not username_taken(
        user.username, except_user_id=user.id, ignore_pending=True
    )


def send_reset_password(email: str) -> None:
    '''Mail a reset link to the active account `email` names. For the anonymous
    forgot-password form, the one caller that has only a typed string. Any
    other account answers as an unknown one: a pending invitee completes its
    invitation, whose token a reset would replace, and a deactivated account
    may not reset.'''
    logger = _logger()
    with Transaction() as transaction:
        user = find_user_by_username(email, transaction.run_raw())
        if not user or user.status_id != UserStatusEnum.ACTIVE.value:
            logger.warning('User does not exist with email: \'%s\'', email)
            raise ItemNotFound('user', {'username': email})
        _mail_reset_link(transaction, user, logger)
    _announce_reset(user, logger)


def send_reset_password_for_account(user_id: int) -> None:
    '''Mail a reset link to the account an admin route has already authorised,
    by id: looking it up again by username could pick a case-only twin.'''
    logger = _logger()
    with Transaction() as transaction:
        user = transaction.find_by_id(User, user_id)
        if not user:
            raise ItemNotFound('user', {'id': user_id})
        _mail_reset_link(transaction, user, logger)
    _announce_reset(user, logger)


def _logger() -> Union[Logger, LoggerAdapter]:
    return g.request_logger if hasattr(g, 'request_logger') else LOG


def _mail_reset_link(
    transaction: Transaction, user: User, logger: Union[Logger, LoggerAdapter]
) -> None:
    token = current_app.user_manager.generate_token(int(user.get_id()))
    reset_password_link = deployment_url('auth.reset_password', token=token)

    email_message = current_app.email_renderer.create_password_reset_message(
        current_user, user, reset_password_link
    )
    logger.info('Sending reset-password email to: \'%s\'', user.username)
    try:
        current_app.notification_service.send_email(email_message)
    except NotificationError:
        error = f'Failed to send reset-password email to: \'{user.username}\''
        logger.error('Failed to send reset-password email to: \'%s\'', user.username)
        raise BadGateway(error)  # pylint: disable=raise-missing-from

    user.reset_password_token = token
    transaction.add_or_update(user, flush=True)


def _announce_reset(user: User, logger: Union[Logger, LoggerAdapter]) -> None:
    # pylint: disable=W0212
    user_forgot_password.send(current_app._get_current_object(), user=user)
    logger.info(
        'Successfully sent reset password email for user with email: \'%s\'',
        user.username,
    )
