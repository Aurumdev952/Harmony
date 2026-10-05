'''Legacy view of `harmony.core.settings` for readers not yet moved to it (BE-2).

Attributes, warnings and errors match the module this replaced, except that a
missing DRUID_HOST raises RuntimeError rather than KeyError.
'''

import os
from typing import Optional

from harmony.core.settings import get_settings, refuse_default_secret
from log import LOG


def getenv(name, default=None):
    '''It's better to know what has been configured and what hasn't!'''
    result = os.environ.get(name, default)
    if result is None or result == '':
        LOG.warning('Environment variable %s not set', name)
    return result


def require_secret(name: str) -> str:
    '''Return environment variable `name`, refusing an unset, blank or default value (SEC-3).'''
    try:
        return refuse_default_secret(name, os.environ.get(name, ''))
    except ValueError as error:
        raise RuntimeError(str(error)) from None


def setting(name: str) -> Optional[str]:
    '''The optional setting `name`, logging a warning when it is unset or empty.'''
    value = getattr(get_settings(), name)
    if value is None or value == '':
        LOG.warning('Environment variable %s not set', name)
    return value


# Loaded at import rather than where Flask reads it: pipeline runs build a Flask
# app in their validate steps, so a lazy check would fail hours in.
DEFAULT_SECRET_KEY = get_settings().DEFAULT_SECRET_KEY.get_secret_value()

# Other
NOREPLY_EMAIL = setting('NOREPLY_EMAIL')
SUPPORT_EMAIL = setting('SUPPORT_EMAIL')

REDIS_HOST = setting('REDIS_HOST')
HASURA_HOST = setting('HASURA_HOST')

DRUID_HOST = get_settings().DRUID_HOST

# How LAST_VALUE is posted (WP-8a, N3): 'extension' (the aggregateLast extension,
# Druid 0.23 with legacy nulls only) or 'native' (Druid's expression aggregator).
# WP-8b makes native the only form and removes this setting (decision 0007, rule 5).
DRUID_LAST_VALUE = os.environ.get('HARMONY_DRUID_LAST_VALUE') or 'extension'
if DRUID_LAST_VALUE not in ('extension', 'native'):
    raise ValueError(
        "HARMONY_DRUID_LAST_VALUE must be 'extension' or 'native', "
        f'not {DRUID_LAST_VALUE!r}'
    )

RENDERBOT_EMAIL = getenv('RENDERBOT_EMAIL', None)
URLBOX_API_KEY = getenv('URLBOX_API_KEY', None)
