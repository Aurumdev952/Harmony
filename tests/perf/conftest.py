"""baseline.py is a standalone script in scripts/perf, not a package; its
tests live here so that ci/pytest_suites.sh runs them, and import it from
there."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'perf'))
