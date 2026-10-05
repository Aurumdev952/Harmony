"""Under CI, hypothesis draws the same examples on every run, so red is reproducible."""

import os

from hypothesis import settings

settings.register_profile(
    'harmony-pipeline-ci', derandomize=True, database=None, deadline=None
)

if os.environ.get('CI'):
    settings.load_profile('harmony-pipeline-ci')
