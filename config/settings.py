import os

from log import LOG


def getenv(name, default=None):
    '''It's better to know what has been configured and what hasn't!'''
    result = os.environ.get(name, default)
    if result is None or result == '':
        LOG.warning('Environment variable %s not set', name)
    return result


# Flask
DEFAULT_SECRET_KEY = os.environ['DEFAULT_SECRET_KEY']

# Other
NOREPLY_EMAIL = getenv('NOREPLY_EMAIL', None)
SUPPORT_EMAIL = getenv('SUPPORT_EMAIL', None)

REDIS_HOST = getenv('REDIS_HOST', '')  # Redis isn't a hard requirement
HASURA_HOST = getenv('HASURA_HOST')  # Hasura is needed for web, but not for pipeline

DRUID_HOST = os.environ['DRUID_HOST']

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
