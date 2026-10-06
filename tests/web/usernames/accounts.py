"""The accounts in the test `user` table."""

from models.alchemy.user import UserStatusEnum

ACTIVE = UserStatusEnum.ACTIVE.value
PENDING = UserStatusEnum.PENDING.value
PASSWORD = 'correct horse battery staple 1A!'
# `user.created` of every account below, in UTC as the database writes it.
ACCOUNTS_CREATED = '2026-01-01 00:00:00.000000'

# (id, username, status, invitation token). Ids give insertion order, which is
# what `first()` returned for an ILIKE pattern before WP-0k.
ACCOUNTS = [
    (1, 'john.doe@moh.gov.rw', ACTIVE, ''),
    # A look-alike registered later: `_` is a LIKE wildcard for `.`.
    (2, 'john_doe@moh.gov.rw', ACTIVE, ''),
    (3, 'Mixed.Case@moh.gov.rw', ACTIVE, ''),
    (4, 'Pending.User@moh.gov.rw', PENDING, 'invite-4'),
    # Usernames are unique only as stored, so these two coexist.
    (5, 'Ann@moh.gov.rw', ACTIVE, ''),
    (6, 'ann@moh.gov.rw', ACTIVE, ''),
    (7, 'percent%sign@moh.gov.rw', ACTIVE, ''),
    (8, 'jane.doe@moh.gov.rw', ACTIVE, ''),
    # Invited after jane.doe, and not yet registered.
    (9, 'jane_doe@moh.gov.rw', PENDING, 'invite-9'),
    # Re-inviting a mixed-case account before WP-0k lowercased the address and
    # added a second, pending account without a password.
    (10, 'Dup.Shell@moh.gov.rw', ACTIVE, ''),
    (11, 'dup.shell@moh.gov.rw', PENDING, 'invite-11'),
]
