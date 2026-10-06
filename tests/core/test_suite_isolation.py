'''Test files from different suites can share one pytest process.

ci/pytest_suites.sh runs each suite in its own process, but `pytest tests/web
tests/core/...` must pass too. Two process globals leaked between them: the Flask
app context the golden harness pushes, and the Api a Flask-Potion resource class
is bound to. The probe plugin records them when the session ends.
'''

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
POLICY = 'tests/core/test_policy_exclusion_keeps_nulls.py'
# The web tests that build the full app (binding Potion resources), push app
# contexts, or read `current_app`.
WEB = [
    'tests/web/test_api_token_issue.py',
    'tests/web/test_graphql_endpoint_removed.py',
    'tests/web/test_query_policy_filter.py',
    'tests/web/test_redis_password.py',
]
CLEAN = {
    'app_context_pushed': False,
    'request_context_pushed': False,
    'query_resource_bound': False,
    'golden_app_cached': False,
}


@pytest.mark.parametrize(
    'paths',
    [[*WEB, POLICY], [POLICY, *WEB]],
    ids=['web-then-policy', 'policy-then-web'],
)
def test_suites_pass_together_and_leave_no_global_state(tmp_path, paths):
    out = tmp_path / 'state.json'
    env = {**os.environ, 'ISOLATION_PROBE_OUT': str(out)}
    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'pytest',
            '-p',
            'tests.core.isolation_probe',
            '-p',
            'no:randomly',
            '-p',
            'no:cacheprovider',
            '-q',
            *paths,
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-3000:]
    assert json.loads(out.read_text()) == CLEAN
