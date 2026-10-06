"""baseline.py is a standalone script in scripts/perf, not a package; its
tests live here so that ci/pytest_suites.sh runs them, and import it from
there."""

import sys
from pathlib import Path

from hypothesis import HealthCheck, settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'perf'))

# No per-example deadline and no too_slow health check: the properties run the
# bootstrap and assert results, not speed, and on a loaded CI host both the
# deadline (as in tests/contract/test_schema.py) and slow example generation
# (FailedHealthCheck at load 72) fail them at random.
settings.register_profile(
    'perf', deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
settings.load_profile('perf')
