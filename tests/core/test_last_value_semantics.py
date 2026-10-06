'''What the native LAST_VALUE aggregator computes, not just what it posts (WP-8a, N3).

`test_last_value_native.py` pins the posted expression text, which cannot catch a
wrong meaning. Here a small evaluator runs the posted `fold`, `combine` and
`finalize` the way Druid's `expression` aggregator does: each segment folds its
rows into `initialValue`, partial results are combined in any order (also when
`subtotalsSpec` re-aggregates finer groups), and the result is finalized. It must
equal the extension's meaning: the inner aggregator over the rows at the latest
time, ties included, and 0 with no rows. The live proof is
`tests/druid/test_last_value_live.py`; this covers shapes the audit dataset
cannot produce, such as rows tied at the latest time in different segments,
which month segments make impossible until WP-8c range-partitions.
'''

import json
import os
import random
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import pytest

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'core-tests-not-a-secret')
os.environ.setdefault('DRUID_HOST', 'http://druid.core-tests.invalid')

# pylint: disable=wrong-import-position
from db.druid.aggregations.last_value_aggregation import native_last_value

Row = Tuple[int, Optional[float]]

INNER = {
    'doubleSum': sum,
    'doubleMax': max,
    'doubleMin': min,
}

_TOKEN = re.compile(
    r'\s*(?:(?P<number>-?\d+(?:\.\d+)?)|(?P<quoted>"(?:[^"\\]|\\.)*")'
    r"|(?P<string>'[^']*')|(?P<name>[A-Za-z_][A-Za-z_0-9]*)|(?P<op>==|[>+(),]))"
)


def _tokens(text: str) -> List[Tuple[str, str]]:
    tokens, position = [], 0
    text = text.strip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        assert match, f'cannot read {text[position:]!r}'
        kind = match.lastgroup
        assert kind is not None
        tokens.append((kind, match.group(kind)))
        position = match.end()
    return tokens


class _Parser:
    '''Parses the expression subset the native aggregator posts into a closure
    over the variable bindings.'''

    def __init__(self, text: str):
        self.tokens = _tokens(text)
        self.position = 0

    def parse(self) -> Callable[[Dict], object]:
        expression = self._comparison()
        assert self.position == len(self.tokens), self.tokens[self.position :]
        return expression

    def _peek(self) -> Tuple[str, str]:
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return ('end', '')

    def _take(self, value: Optional[str] = None) -> Tuple[str, str]:
        token = self._peek()
        assert value is None or token[1] == value, (token, value)
        self.position += 1
        return token

    def _comparison(self):
        left = self._sum()
        if self._peek()[1] in ('>', '=='):
            op = self._take()[1]
            right = self._sum()
            if op == '>':
                return lambda b: float(left(b) > right(b))
            return lambda b: float(left(b) == right(b))
        return left

    def _sum(self):
        terms = [self._primary()]
        while self._peek()[1] == '+':
            self._take('+')
            terms.append(self._primary())
        if len(terms) == 1:
            return terms[0]
        return lambda b: sum(term(b) for term in terms)

    def _primary(self):
        kind, value = self._take()
        if kind == 'number':
            number = float(value)
            return lambda b: number
        if kind == 'string':
            text = value[1:-1]
            return lambda b: text
        if kind == 'quoted':
            name = json.loads(value)
            return lambda b: b[name]
        assert kind == 'name', (kind, value)
        if self._peek()[1] != '(':
            return lambda b: b[value]
        self._take('(')
        args = [self._comparison()]
        while self._peek()[1] == ',':
            self._take(',')
            args.append(self._comparison())
        self._take(')')
        return _function(value, args)


def _function(name: str, args: Sequence[Callable]):
    if name == 'if':
        condition, then, otherwise = args
        return lambda b: then(b) if condition(b) else otherwise(b)
    if name == 'array':
        return lambda b: tuple(arg(b) for arg in args)
    if name == 'array_offset':
        array, index = args
        return lambda b: array(b)[int(index(b))]
    if name == 'cast':
        value, target = args
        return lambda b: float(value(b)) if target(b) == 'DOUBLE' else value(b)
    if name == 'nvl':
        value, default = args
        return lambda b: default(b) if value(b) is None else value(b)
    if name == 'greatest':
        return lambda b: max(arg(b) for arg in args)
    if name == 'least':
        return lambda b: min(arg(b) for arg in args)
    raise AssertionError(f'unexpected function {name}')


class _Druid:
    '''Druid's expression aggregator, as far as LAST_VALUE uses it.'''

    def __init__(self, name: str, inner_type: str, field: str = 'sum'):
        self.spec = native_last_value(name, {'type': inner_type, 'fieldName': field})
        self.name = name
        self.field = field
        self.accumulator = self.spec['accumulatorIdentifier']
        self.initial = _Parser(self.spec['initialValue']).parse()({})
        self.fold_expression = _Parser(self.spec['fold']).parse()
        self.combine_expression = _Parser(self.spec['combine']).parse()
        self.finalize_expression = _Parser(self.spec['finalize']).parse()

    def fold(self, rows: Sequence[Row]):
        accumulator = self.initial
        for time, value in rows:
            accumulator = self.fold_expression(
                {self.accumulator: accumulator, '__time': time, self.field: value}
            )
        return accumulator

    def combine(self, partials: Sequence):
        accumulator = self.initial
        for partial in partials:
            accumulator = self.combine_expression(
                {self.accumulator: accumulator, self.name: partial}
            )
        return accumulator

    def finalize(self, accumulator) -> float:
        return self.finalize_expression({'o': accumulator})


def _extension(rows: Sequence[Row], inner_type: str) -> float:
    '''The aggregateLast extension's meaning on legacy Druid.'''
    if not rows:
        return 0.0
    latest = max(time for time, _ in rows)
    values = [value or 0.0 for time, value in rows if time == latest]
    return float(INNER[inner_type](values))


def _random_rows(rng: random.Random) -> List[Row]:
    # Few distinct times, so ties at the latest time are common.
    times = [1514764800000 + day * 86400000 for day in range(rng.randint(1, 4))]
    rows = []
    for _ in range(rng.randint(0, 12)):
        value = rng.choice([None, 0.0, 1.0, 2.5, -3.0, 7.0, 1e15])
        rows.append((rng.choice(times), value))
    return rows


def _split(rng: random.Random, rows: List[Row], parts: int) -> List[List[Row]]:
    shuffled = rows[:]
    rng.shuffle(shuffled)
    split: List[List[Row]] = [[] for _ in range(parts)]
    for row in shuffled:
        split[rng.randrange(parts)].append(row)
    return split


@pytest.mark.parametrize('inner_type', sorted(INNER))
def test_rows_in_one_segment(inner_type):
    rng = random.Random(f'one-{inner_type}')
    druid = _Druid('last', inner_type)
    for _ in range(300):
        rows = _random_rows(rng)
        rng.shuffle(rows)
        assert druid.finalize(druid.fold(rows)) == _extension(rows, inner_type), rows


@pytest.mark.parametrize('inner_type', sorted(INNER))
def test_ties_across_segments_combine(inner_type):
    '''Rows at the latest time can sit in different segments of one time chunk
    (several shards, or range partitions after WP-8c); `combine` adds them up
    (or takes the max or min) in any merge order, skipping empty segments.'''
    rng = random.Random(f'segments-{inner_type}')
    druid = _Druid('last', inner_type)
    tied_across = 0
    for _ in range(300):
        rows = _random_rows(rng)
        segments = _split(rng, rows, rng.randint(2, 4))
        partials = [druid.fold(segment) for segment in segments]
        rng.shuffle(partials)
        assert druid.finalize(druid.combine(partials)) == _extension(
            rows, inner_type
        ), segments
        if rows:
            latest = max(time for time, _ in rows)
            tied_across += (
                sum(any(t == latest for t, _ in segment) for segment in segments) > 1
            )
    assert tied_across > 50


@pytest.mark.parametrize('inner_type', sorted(INNER))
def test_subtotals_reaggregate_finer_groups(inner_type):
    '''`subtotalsSpec` merges the finer groups' partials with `combine`: a state
    subtotal is the latest value over all of its municipalities' rows.'''
    rng = random.Random(f'subtotals-{inner_type}')
    druid = _Druid('last', inner_type)
    for _ in range(300):
        groups = [_random_rows(rng) for _ in range(rng.randint(1, 5))]
        partials = [druid.fold(group) for group in groups]
        everything = [row for group in groups for row in group]
        assert druid.finalize(druid.combine(partials)) == _extension(
            everything, inner_type
        ), groups


@pytest.mark.parametrize(('name', 'field'), [('__acc', 'sum'), ('x', '__acc')])
def test_names_like_the_accumulator_keep_the_meaning(name, field):
    druid = _Druid(name, 'doubleSum', field)
    rows = [(2, 1.0), (1, 5.0), (2, 2.0)]
    segments = [[rows[0]], [rows[1]], [rows[2]]]
    partials = [druid.fold(segment) for segment in segments]
    assert druid.finalize(druid.combine(partials)) == 3.0


def test_the_evaluator_rejects_a_wrong_meaning():
    '''A combine that keeps only one tied partial must fail these tests.'''
    druid = _Druid('last', 'doubleSum')
    druid.combine_expression = _Parser(
        druid.spec['combine'].replace('array_offset(__acc, 1) + ', '0.0 + ', 1)
    ).parse()
    partials = [druid.fold([(2, 1.0)]), druid.fold([(2, 2.0)])]
    assert druid.finalize(druid.combine(partials)) != _extension(
        [(2, 1.0), (2, 2.0)], 'doubleSum'
    )
