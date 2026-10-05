# Python 3.10 removed the ABC aliases on `collections` (`collections.Mapping`, ...).
# These paths reach them only when called, so an import sweep cannot find them.
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from web.server.potion import managers
from web.server.util.util import (
    assert_iterable,
    assert_mapping,
    assert_non_string_iterable,
    deep_update,
)


def test_deep_update_merges_nested_mappings_and_extends_lists() -> None:
    source = {'foo': {'bar': [1], 'baz': 2, 'quz': 3}, 'do': 1}
    other = {'foo': {'bar': [4], 'qux': 2, 'baz': [10]}}

    assert deep_update(source, other) == {
        'foo': {'bar': [1, 4], 'baz': [10], 'quz': 3, 'qux': 2},
        'do': 1,
    }


def test_assert_iterable_accepts_sequences_and_rejects_strings() -> None:
    assert_iterable([1, 2])
    assert_non_string_iterable((1, 2))
    with pytest.raises(ValueError, match="NOT of type: 'string'"):
        assert_iterable('abc')
    with pytest.raises(ValueError, match="must be of type: 'iterable'"):
        assert_non_string_iterable(3)


def test_assert_mapping_accepts_dicts_and_rejects_pairs() -> None:
    # PythonModel.deserialize (models/python/base.py) calls this on every payload.
    assert_mapping({'a': 1})
    with pytest.raises(ValueError, match="must be of type: 'mapping'"):
        assert_mapping([('a', 1)])


class _FakeTransaction:
    def __init__(self, **_kwargs: Any) -> None:
        pass

    def __enter__(self) -> _FakeTransaction:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def find_by_id(self, _model: object, _id: object) -> SimpleNamespace:
        return SimpleNamespace()

    def add_or_update(self, item: object, flush: bool = False) -> object:
        return item


class _Manager(managers.AuthorizationResourceManager):
    def create_authorization_model(self, item, authorization_model):
        pass

    def update_authorization_model(self, item, changes, authorization_item):
        pass


def test_potion_update_flags_json_changes_as_modified(monkeypatch) -> None:
    # The dashboard and alert PATCH path: JSON columns must be flagged or the
    # change is not persisted.
    flagged: list[str] = []
    monkeypatch.setattr(managers, 'Transaction', _FakeTransaction)
    monkeypatch.setattr(
        managers, 'flag_modified', lambda _item, key: flagged.append(key)
    )
    manager = object.__new__(_Manager)
    manager.resource = object()
    manager.target_model_authorization_attribute = 'resource_id'
    manager.authorization_model = object
    item = SimpleNamespace(resource_id=7, specification={'old': 1}, title='old')

    manager.update(item, {'specification': {'new': 2}, 'title': 'new'})

    assert flagged == ['specification']
    assert item.specification == {'new': 2}
    assert item.title == 'new'
