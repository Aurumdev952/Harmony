'''The hierarchical part of a user's row-level policy is one fixed Druid filter,
whatever order its dimensions and values arrive in (INV-3).

Included values are ORed across the hierarchy: a user who may see one state or
one municipality sees both. Excluded values always restrict: they are ANDed onto
that union, whichever dimension they sit on. Before this fix the builder applied
`|=` for includes and `&=` for excludes in dict iteration order, which follows
set order and so PYTHONHASHSEED: one policy with an include on StateName and an
exclude on MunicipalityName became `Kano AND NOT X` in one process and
`NOT X OR Kano` (nearly every row) in another.

Synthetic policies; nothing leaves the process except the interpreters started
with other hash seeds.
'''

import itertools
import json
import os
import subprocess
import sys

import pytest

# config/settings.py reads these at import time; the values are test-only placeholders.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-web-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('ZEN_ENV', 'harmony_demo')

# pylint: disable=wrong-import-position
from pydruid.utils.filters import Filter

from db.druid import util as druid_util
from db.druid.util import EmptyFilter
from web.server.routes.views.query_policy import (
    NO_FILTER_VAL,
    _construct_hierarchical_filter,
)

# The repository root: db/druid/util.py is three levels down.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(druid_util.__file__)))


def _in(dimension, values):
    return {'dimension': dimension, 'type': 'in', 'values': values}


def _excluded(dimension, values):
    # Built the way the policy code builds an exclusion, so the leaf follows
    # whatever null handling `~Filter` has; this test pins how leaves combine.
    return Filter.build_filter(~Filter(type='in', dimension=dimension, values=values))


def _no_value(dimension):
    return {'dimension': dimension, 'type': 'selector', 'value': NO_FILTER_VAL}


def _entry(include=(), exclude=(), all_values=False):
    return {
        'include': list(include),
        'exclude': list(exclude),
        'all_values': all_values,
    }


# name -> (dimension entries, the one filter every order must build)
CASES = {
    'include_on_one_exclude_on_another_is_anded': (
        {
            'StateName': _entry(include=['Kano']),
            'MunicipalityName': _entry(exclude=['X']),
        },
        {
            'type': 'and',
            'fields': [
                _in('StateName', ['Kano']),
                _excluded('MunicipalityName', ['X']),
            ],
        },
    ),
    'includes_are_ored_and_excludes_restrict_the_union': (
        {
            'StateName': _entry(include=['Lagos', 'Kano'], exclude=['Abuja']),
            'MunicipalityName': _entry(include=['M2', 'M1']),
            'WardName': _entry(exclude=['W9', 'W1']),
        },
        {
            'type': 'and',
            'fields': [
                {
                    'type': 'or',
                    'fields': [
                        _in('MunicipalityName', ['M1', 'M2']),
                        _in('StateName', ['Kano', 'Lagos']),
                    ],
                },
                {
                    'type': 'and',
                    'fields': [
                        _excluded('StateName', ['Abuja']),
                        _excluded('WardName', ['W1', 'W9']),
                    ],
                },
            ],
        },
    ),
    'includes_only_are_ored': (
        {
            'StateName': _entry(include=['Kano']),
            'MunicipalityName': _entry(include=['M1']),
        },
        {
            'type': 'or',
            'fields': [_in('MunicipalityName', ['M1']), _in('StateName', ['Kano'])],
        },
    ),
    'an_exclude_does_not_open_a_dimension_without_policy': (
        {
            'StateName': _entry(exclude=['X']),
            'MunicipalityName': _entry(),
        },
        {
            'type': 'and',
            'fields': [_no_value('MunicipalityName'), _excluded('StateName', ['X'])],
        },
    ),
    'excludes_only_restrict_everything': (
        {
            'StateName': _entry(exclude=['X']),
            'MunicipalityName': _entry(exclude=['Y']),
        },
        {
            'type': 'and',
            'fields': [
                _excluded('MunicipalityName', ['Y']),
                _excluded('StateName', ['X']),
            ],
        },
    ),
    'all_values_anywhere_lifts_the_hierarchy': (
        {
            'StateName': _entry(include=['Kano']),
            'MunicipalityName': _entry(exclude=['X']),
            'WardName': _entry(all_values=True),
        },
        None,
    ),
}


def _filter_map(entries, dimension_order, reverse_values):
    '''The builder's input with dimensions inserted in `dimension_order` and each
    value set built from its list forwards or backwards.'''
    filter_map = {}
    for dimension in dimension_order:
        entry = entries[dimension]
        step = -1 if reverse_values else 1
        filter_map[dimension] = {
            'include': set(entry['include'][::step]),
            'exclude': set(entry['exclude'][::step]),
            'all_values': entry['all_values'],
        }
    return filter_map


def _built(filter_map):
    druid_filter = _construct_hierarchical_filter(filter_map)
    if isinstance(druid_filter, EmptyFilter):
        return None
    return Filter.build_filter(druid_filter)


@pytest.mark.parametrize('name', sorted(CASES))
def test_every_order_builds_the_same_filter(name):
    entries, expected = CASES[name]

    built = {
        json.dumps(_built(_filter_map(entries, order, reverse)), sort_keys=True)
        for order in itertools.permutations(entries)
        for reverse in (False, True)
    }

    assert built == {json.dumps(expected, sort_keys=True)}


PROBE = '''
import json, sys
from pydruid.utils.filters import Filter
from web.server.routes.views.query_policy import _construct_hierarchical_filter
entries = json.loads(sys.argv[1])
filter_map = {
    dimension: {
        'include': set(entry['include']),
        'exclude': set(entry['exclude']),
        'all_values': entry['all_values'],
    }
    for dimension, entry in entries.items()
}
print(json.dumps(Filter.build_filter(_construct_hierarchical_filter(filter_map)), sort_keys=True))
'''


def test_every_hash_seed_builds_the_same_filter():
    # Set and dict order follow PYTHONHASHSEED, so the check that matters runs
    # in interpreters with different seeds.
    entries, expected = CASES['includes_are_ored_and_excludes_restrict_the_union']
    outputs = set()
    for seed in ('0', '1', '2', '3', '4', '5'):
        result = subprocess.run(
            [sys.executable, '-c', PROBE, json.dumps(entries)],
            cwd=ROOT,
            env={**os.environ, 'PYTHONHASHSEED': seed, 'PYTHONPATH': ROOT},
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        outputs.add(result.stdout.strip().splitlines()[-1])

    assert outputs == {json.dumps(expected, sort_keys=True)}
