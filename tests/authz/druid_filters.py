'''Order-independent, compact form of pydruid filters for comparison.

`in` values and `and`/`or` operands come out of Python sets, so their order
changes with PYTHONHASHSEED. The compact form sorts them; nothing else is
normalised.

    selector  -> {eq: [dimension, value]}
    in        -> {in: [dimension, [sorted values]]}
    not       -> {not: <filter>}
    and / or  -> {and: [sorted filters]} / {or: [...]}
    no filter -> None
'''

from __future__ import annotations

import json

from pydruid.utils.filters import Filter

from db.druid.util import EmptyFilter


def _sort_key(value) -> str:
    return json.dumps(value, sort_keys=True)


def compact_dict(raw: dict):
    kind = raw['type']
    if kind == 'selector':
        return {'eq': [raw['dimension'], raw['value']]}
    if kind == 'in':
        return {'in': [raw['dimension'], sorted(raw['values'])]}
    if kind == 'not':
        return {'not': compact_dict(raw['field'])}
    if kind in ('and', 'or'):
        return {kind: sorted((compact_dict(f) for f in raw['fields']), key=_sort_key)}
    raise AssertionError(f'unexpected filter type {kind}: {raw}')


def compact(druid_filter):
    if druid_filter is None or isinstance(druid_filter, EmptyFilter):
        return None
    return compact_dict(Filter.build_filter(druid_filter))


def normalise_expected(expected):
    '''Sorts a hand-written expectation the same way `compact` sorts output.'''
    if expected is None:
        return None
    ((kind, body),) = expected.items()
    if kind == 'in':
        return {'in': [body[0], sorted(body[1])]}
    if kind == 'not':
        return {'not': normalise_expected(body)}
    if kind in ('and', 'or'):
        return {kind: sorted((normalise_expected(f) for f in body), key=_sort_key)}
    return expected
