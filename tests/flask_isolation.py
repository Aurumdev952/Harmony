'''Undo the process-global Flask state a test leaves behind, so test files from
different suites can share one pytest process.

Two globals leak: Flask's context stacks (a pushed app or request context makes
`current_app` another test's app), and Flask-Potion's binding of each Resource
class to the Api that registered it first (`Resource.api`), after which any
other Api refuses the class. The golden harness also caches the app it built
and pushed (`harness._APP`).
'''

import sys
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Tuple

import flask
from flask_potion import Resource


def _resource_classes() -> List[type]:
    found, pending = [], [Resource]
    while pending:
        cls = pending.pop()
        for subclass in cls.__subclasses__():
            found.append(subclass)
            pending.append(subclass)
    return found


def _bindings() -> Dict[type, Tuple[Any, Any]]:
    return {
        cls: (cls.__dict__.get('api'), cls.__dict__.get('route_prefix'))
        for cls in _resource_classes()
    }


def _depth(stack) -> int:
    return len(getattr(stack._local, 'stack', None) or [])  # pylint: disable=protected-access


@contextmanager
def restored_flask_globals() -> Iterator[None]:
    '''Pop the contexts pushed inside the block, and put back the Potion bindings
    and the golden harness's cached app as they were before it.'''
    # pylint: disable=protected-access
    request_depth = _depth(flask._request_ctx_stack)
    app_depth = _depth(flask._app_ctx_stack)
    bindings = _bindings()
    harness = sys.modules.get('tests.golden.harness')
    golden_app = getattr(harness, '_APP', None)
    try:
        yield
    finally:
        while _depth(flask._request_ctx_stack) > request_depth:
            flask._request_ctx_stack.top.pop()
        while _depth(flask._app_ctx_stack) > app_depth:
            flask._app_ctx_stack.top.pop()
        for cls in _resource_classes():
            api, route_prefix = bindings.get(cls, (None, None))
            cls.api, cls.route_prefix = api, route_prefix
        harness = sys.modules.get('tests.golden.harness')
        if harness is not None:
            harness._APP = golden_app
