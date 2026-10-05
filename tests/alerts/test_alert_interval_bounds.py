'''An alert with a granularity that has no interval bounds raises, also under -O.'''

import os
from datetime import datetime

import pytest

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'alert-tests-not-a-secret')
os.environ.setdefault('DRUID_HOST', 'http://druid.alert-tests.invalid')

# pylint: disable=wrong-import-position
from data.alerts.alert import AlertLatestDate, get_interval_bounds

LATEST = AlertLatestDate(max_date=datetime(2024, 3, 15), min_date=datetime(2024, 3, 1))


@pytest.mark.parametrize('granularity', ['quarter', 'year', None])
def test_unsupported_granularity_raises(granularity):
    with pytest.raises(ValueError, match='is not supported'):
        get_interval_bounds(LATEST, granularity)
