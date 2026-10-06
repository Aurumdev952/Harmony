"""baseline.py is a standalone script in scripts/perf, not a package; its
tests live here so that ci/pytest_suites.sh runs them, and import it from
there."""

import sys
from pathlib import Path

from hypothesis import settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'perf'))

# No per-example deadline: the properties run the bootstrap and assert results,
# not speed, and a wall-clock deadline fails at random on a loaded CI host (as
# in tests/contract/test_schema.py).
settings.register_profile('perf', deadline=None)
settings.load_profile('perf')
