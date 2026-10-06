'''Undo the process-global Flask state a test leaves behind, so test files from
different suites can share one pytest process.

Two globals leak: Flask's context stacks (a pushed app or request context makes
`current_app` another test's app), and Flask-Potion's binding of each Resource
class to the Api that registered it first (`Resource.api`), after which any
other Api refuses the class. Registering also copies the class's relation routes
into its own `routes`, after which another Api registers them twice; a class
first defined inside the block (a module the full app imports) gets back the
routes it had before its first registration. The golden harness also caches the
app it built and pushed (`harness._APP`).
'''

import sys
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Tuple

import flask
from flask_potion import Api, Resource

# Each resource class's routes before any Api first registered it.
_UNREGISTERED_ROUTES: Dict[type, Dict[str, Any]] = {}
_add_resource = Api.add_resource


def _add_resource_recording_routes(self, resource):
    _UNREGISTERED_ROUTES.setdefault(resource, dict(resource.routes))
    return _add_resource(self, resource)


Api.add_resource = _add_resource_recording_routes


def _resource_classes() -> List[type]:
    found, pending = [], [Resource]
    while pending:
        cls = pending.pop()
        for subclass in cls.__subclasses__():
            found.append(subclass)
            pending.append(subclass)
    return found


def _bindings() -> Dict[type, Tuple[Any, Any, Any]]:
    return {
        cls: (
            cls.__dict__.get('api'),
            cls.__dict__.get('route_prefix'),
            dict(cls.__dict__.get('routes') or {}),
        )
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
            if cls in bindings:
                cls.api, cls.route_prefix, cls.routes = bindings[cls]
            else:
                cls.api, cls.route_prefix = None, None
                if cls in _UNREGISTERED_ROUTES:
                    cls.routes = dict(_UNREGISTERED_ROUTES[cls])
        harness = sys.modules.get('tests.golden.harness')
        if harness is not None:
            harness._APP = golden_app
