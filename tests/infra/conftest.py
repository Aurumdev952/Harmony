import sys

# The standalone tools tested here (prod/browser_share) target CPython 3.13, while
# the app environment stays on 3.9 until WP-3b. CI runs this directory in its own
# 3.13 job, so the 3.9 run skips collecting it instead of failing on imports.
if sys.version_info < (3, 13):
    collect_ignore_glob = ["test_*.py"]
