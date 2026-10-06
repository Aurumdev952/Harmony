'''Every seeded role and an anonymous visitor against requests.yaml.'''

from __future__ import annotations

import os

import pytest
import yaml

from tests.authz.http.stack import outcome
from tests.authz.principals import principal_specs
from tests.authz.table import expand

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, 'requests.yaml')) as _stream:
    _TABLE = yaml.safe_load(_stream)

PRINCIPALS = ['anonymous'] + [
    name for name in principal_specs() if name.startswith('role:')
]


def _rows():
    for entry in _TABLE['requests']:
        allowed = expand(entry['allow'], principal_specs()) & set(PRINCIPALS)
        for principal in PRINCIPALS:
            if principal == 'anonymous':
                expected = entry['anonymous']
            elif principal in allowed:
                expected = entry['allowed']
            else:
                expected = entry['denied']
            yield principal, entry['request'], expected


ROWS = list(_rows())


@pytest.mark.parametrize(
    'principal,request_line,expected',
    ROWS,
    ids=[f'{p}|{r}|{e}' for p, r, e in ROWS],
)
def test_request_outcome(principal, request_line, expected, stack):
    method, path = request_line.split(' ', 1)
    response = stack.request(stack.session_for(principal), method, path)
    assert outcome(response) == expected
