import warnings
from datetime import date, timedelta

import pandas as pd

starts = [date(2015, 1, 1) + timedelta(days=17 * i) for i in range(120)]
checked = 0
for granularity in ('day', 'week', 'month', 'quarter'):
    for start in starts:
        for span in (1, 30, 400, 1500):
            first = f'{start}T00:00:00.000Z'
            last = f'{start + timedelta(days=span)}T00:00:00.000Z'
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                old = [
                    p.start_time
                    for p in pd.period_range(first, last, freq=granularity[0])
                ]
            with warnings.catch_warnings():
                warnings.simplefilter('error')
                new = [
                    p.start_time
                    for p in pd.period_range(first, last, freq=granularity[0].upper())
                ]
            assert old == new, (granularity, first, last)  # noqa: S101 (check script)
            checked += 1
print('identical', checked, 'ranges; no warning with upper-case aliases')
