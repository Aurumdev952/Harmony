'''pytest plugin for test_suite_isolation: at the end of the session, write the
process-global state that tests can leak to the JSON file named by
ISOLATION_PROBE_OUT.'''

import json
import os
import sys


def pytest_sessionfinish(session, exitstatus):  # pylint: disable=unused-argument
    # pylint: disable=import-outside-toplevel
    import flask

    query_models = sys.modules.get('web.server.api.query.query_models')
    harness = sys.modules.get('tests.golden.harness')
    state = {
        'app_context_pushed': flask.has_app_context(),
        'request_context_pushed': flask.has_request_context(),
        'query_resource_bound': getattr(
            getattr(query_models, 'QueryResource', None), 'api', None
        )
        is not None,
        'golden_app_cached': getattr(harness, '_APP', None) is not None,
    }
    with open(os.environ['ISOLATION_PROBE_OUT'], 'w', encoding='utf-8') as out:
        json.dump(state, out)
