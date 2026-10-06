# Calls each helper that used a removed `collections` ABC alias and prints OK or the
# error. Run by call_probe.sh inside a web image.
from types import SimpleNamespace

from web.server.potion import managers
from web.server.util.util import assert_iterable, assert_mapping, deep_update


def run(name, fn):
    try:
        fn()
        print(f'{name}\tOK')
    except Exception as e:
        print(f'{name}\tERR {type(e).__name__}: {e}')


class _Transaction:
    def __init__(self, **_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def find_by_id(self, *_):
        return SimpleNamespace()

    def add_or_update(self, item, flush=False):
        return item


class _Manager(managers.AuthorizationResourceManager):
    def create_authorization_model(self, item, authorization_model):
        pass

    def update_authorization_model(self, item, changes, authorization_item):
        pass


def potion_update():
    managers.Transaction = _Transaction
    managers.flag_modified = lambda *_: None
    manager = object.__new__(_Manager)
    manager.resource = object()
    manager.target_model_authorization_attribute = 'resource_id'
    manager.authorization_model = object
    item = SimpleNamespace(resource_id=1, specification={})
    manager.update(item, {'specification': {'a': 1}})


run('deep_update', lambda: deep_update({'a': {'b': [1]}}, {'a': {'b': [2]}}))
run('assert_iterable', lambda: assert_iterable([1]))
run('assert_mapping', lambda: assert_mapping({}))
run('AuthorizationResourceManager.update', potion_update)
