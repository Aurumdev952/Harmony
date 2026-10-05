'''Deterministic stand-in for a Druid broker, used only when recording fixtures.

Given the exact native query the app posts, it answers with rows shaped the way
Druid 0.23 answers: array rows for groupBy (`resultAsArray`), `{timestamp, result}`
objects for timeseries, subtotal blocks in `subtotalsSpec` order, each block sorted
by time then dimension values with nulls first.

The rows are drawn from a small table of facts: a sample of harmony_demo
locations crossed with the yellow fever dimensions and the deployment's real field
ids. The query filter selects facts, so a policy or a filter narrows the rows, and
a field id the deployment does not have matches nothing. Within a row, a filtered
aggregator is zero, and its count zero, when none of the row's facts pass its
filter. Metric values are pseudo-random, seeded from the case name and the query's
structure, so re-recording an unchanged query yields identical bytes.

Anything the cases do not use raises NotImplementedError rather than guessing.
The replay test never calls this module: it reads the frozen
`druid_response.json`.
'''

import hashlib
import json
import random
from datetime import date, datetime, timedelta, timezone
from itertools import product
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MAX_ROWS = 5000
DETAIL_ROW_BUDGET = 300

# (StateName, StateID, StateLat, StateLon, MunicipalityName, MunicipalityID,
# MunicipalityLat, MunicipalityLon), from pipeline/harmony_demo/static_data. The last
# Acre row has no municipality: data reported at state level.
LOCATIONS = [
    (
        'Acre',
        '1',
        '-9.128693',
        '-71.973581',
        'Rio Branco',
        '120040',
        '-9.974',
        '-67.8076',
    ),
    (
        'Acre',
        '1',
        '-9.128693',
        '-71.973581',
        'Cruzeiro do Sul',
        '120020',
        '-7.6307',
        '-72.6704',
    ),
    ('Acre', '1', '-9.128693', '-71.973581', None, None, None, None),
    ('Pará', '14', '-3.974166', '-52.751945', 'Belém', '150140', '-1.4558', '-48.4902'),
    (
        'Pará',
        '14',
        '-3.974166',
        '-52.751945',
        'Conceição do Araguaia',
        '150270',
        '-8.2578',
        '-49.2647',
    ),
    (
        'Roraima',
        '23',
        '1.989233',
        '-61.330109',
        'Alto Alegre',
        '140005',
        '2.9858',
        '-61.3071',
    ),
    (
        'Roraima',
        '23',
        '1.989233',
        '-61.330109',
        'Pacaraima',
        '140045',
        '4.4799',
        '-61.1477',
    ),
]
LOCATION_DIMENSIONS = (
    'StateName',
    'StateID',
    'StateLat',
    'StateLon',
    'MunicipalityName',
    'MunicipalityID',
    'MunicipalityLat',
    'MunicipalityLon',
)
CATEGORICAL_VALUES = {
    'Sex': ['F', 'M'],
    'Age': ['15-49', '50+'],
    'Death': ['0', '1'],
    'source': ['yellow_fever'],
}

COUNT_SUFFIX = '__count'
INT_AGGREGATORS = {'longSum', 'longMin', 'longMax'}

Fact = Dict[str, Optional[str]]


def _demo_field_ids() -> List[str]:
    # pylint: disable=import-outside-toplevel
    from config.harmony_demo.indicators import VALID_FIELDS

    return sorted(VALID_FIELDS)


def _facts(extra_fields: Sequence[str] = ()) -> List[Fact]:
    facts = []
    for location, sex, age, death, source, field in product(
        LOCATIONS,
        CATEGORICAL_VALUES['Sex'],
        CATEGORICAL_VALUES['Age'],
        CATEGORICAL_VALUES['Death'],
        CATEGORICAL_VALUES['source'],
        _demo_field_ids() + list(extra_fields),
    ):
        fact = dict(zip(LOCATION_DIMENSIONS, location))
        fact.update(Sex=sex, Age=age, Death=death, source=source, field=field)
        facts.append(fact)
    return facts


def _seed(case_name: str, query: dict) -> int:
    '''Seed from the parts of the query that decide the result's shape and size, not
    from context or ordering, so adding a timeout or running sub-queries concurrently
    does not change the recorded data.'''
    structure = {
        'case': case_name,
        'queryType': query.get('queryType'),
        'dimensions': query.get('dimensions'),
        'aggregations': sorted(
            aggregator_name(a) for a in query.get('aggregations', [])
        ),
        'postAggregations': sorted(
            p['name'] for p in query.get('postAggregations', [])
        ),
        'granularity': query.get('granularity'),
        'intervals': query.get('intervals'),
        'subtotalsSpec': query.get('subtotalsSpec'),
    }
    digest = hashlib.sha256(json.dumps(structure, sort_keys=True).encode()).digest()
    return int.from_bytes(digest[:8], 'big')


def _matches(druid_filter: Optional[dict], fact: Fact) -> bool:
    if not druid_filter:
        return True
    kind = druid_filter['type']
    if kind == 'and':
        return all(_matches(f, fact) for f in druid_filter['fields'])
    if kind == 'or':
        return any(_matches(f, fact) for f in druid_filter['fields'])
    if kind == 'not':
        return not _matches(druid_filter['field'], fact)
    if kind == 'interval':
        return True
    value = fact[druid_filter['dimension']]
    if kind == 'selector':
        expected = druid_filter['value']
        if expected in (None, ''):
            return value is None
        return value == expected
    if kind == 'in':
        values = druid_filter['values']
        if value is None:
            return None in values or '' in values
        return value in values
    raise NotImplementedError(f'synth cannot evaluate filter type {kind!r}')


def _parse_interval(interval: str) -> Tuple[date, date]:
    start, end = interval.split('/')
    return (date.fromisoformat(start[:10]), date.fromisoformat(end[:10]))


def _floor(day: date, granularity: str) -> date:
    if granularity == 'day':
        return day
    if granularity == 'week':
        return day - timedelta(days=day.weekday())
    if granularity == 'month':
        return day.replace(day=1)
    if granularity == 'quarter':
        return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
    if granularity == 'year':
        return date(day.year, 1, 1)
    raise NotImplementedError(f'synth cannot bucket granularity {granularity!r}')


def _days(intervals: Sequence[str]) -> Iterable[date]:
    for interval in intervals:
        start, end = _parse_interval(interval)
        day = start
        while day < end:
            yield day
            day += timedelta(days=1)


def _time_dimension_value(spec: dict, day: date) -> str:
    extraction = spec['extractionFn']
    if extraction['type'] != 'timeFormat':
        raise NotImplementedError(f'synth cannot evaluate extraction {extraction}')
    bucket = _floor(day, extraction['granularity'])
    return (
        extraction['format']
        .replace('YYYY', f'{bucket.year:04d}')
        .replace('MM', f'{bucket.month:02d}')
        .replace('dd', f'{bucket.day:02d}')
    )


def _dimension_name(spec: Any) -> str:
    return spec if isinstance(spec, str) else spec['outputName']


def _is_time_dimension(spec: Any) -> bool:
    return isinstance(spec, dict) and spec.get('dimension') == '__time'


def _timestamp_ms(day: date) -> int:
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return int(midnight.timestamp()) * 1000


def _timestamp_iso(day: date) -> str:
    return f'{day.isoformat()}T00:00:00.000Z'


def _inner_aggregator(aggregator: dict) -> dict:
    while aggregator.get('type') == 'filtered':
        aggregator = aggregator['aggregator']
    return aggregator


def aggregator_name(aggregator: dict) -> str:
    return aggregator.get('name') or _inner_aggregator(aggregator)['name']


def _aggregator_filter(aggregator: dict) -> Optional[dict]:
    return aggregator['filter'] if aggregator.get('type') == 'filtered' else None


class _Metrics:
    def __init__(
        self, query: dict, rng: random.Random, special_values: bool, dense: bool
    ):
        self.aggregations = query.get('aggregations', [])
        self.post_aggregations = query.get('postAggregations', [])
        self.rng = rng
        self.special_values = special_values
        self.dense = dense

    @property
    def names(self) -> List[str]:
        return [aggregator_name(a) for a in self.aggregations] + [
            p['name'] for p in self.post_aggregations
        ]

    def _number(self) -> float:
        if self.rng.random() < 0.7:
            return float(self.rng.randint(1, 400))
        return round(self.rng.uniform(0.5, 400), 2)

    def row(self, facts: Sequence[Fact]) -> List[Any]:
        '''One row's metric values. An aggregator whose filter no fact passes is
        empty; so, at random unless `dense`, is any other filter, as a bucket with
        no reports. Aggregators sharing a filter (a value and its `__count`) share
        emptiness.'''
        empty: Dict[str, bool] = {}
        values: Dict[str, Any] = {}
        for aggregator in self.aggregations:
            name = aggregator_name(aggregator)
            agg_filter = _aggregator_filter(aggregator)
            key = json.dumps(agg_filter, sort_keys=True)
            if key not in empty:
                empty[key] = not any(_matches(agg_filter, fact) for fact in facts) or (
                    not self.dense and self.rng.random() < 0.15
                )
            kind = _inner_aggregator(aggregator)['type']
            if name.endswith(COUNT_SUFFIX) or kind in INT_AGGREGATORS:
                values[name] = 0 if empty[key] else self.rng.randint(1, 60)
            else:
                values[name] = 0.0 if empty[key] else self._number()
        all_empty = bool(empty) and all(empty.values())
        for post_aggregator in self.post_aggregations:
            name = post_aggregator['name']
            if self.special_values and self.rng.random() < 0.3:
                values[name] = self.rng.choice(['NaN', 'Infinity', '-Infinity', None])
            else:
                values[name] = 0.0 if all_empty else round(self.rng.uniform(0, 1000), 4)
        return [values[name] for name in self.names]


def _sort_key(values: Sequence[Optional[str]]) -> Tuple:
    return tuple((value is not None, value or '') for value in values)


def synthesize(case_name: str, query: dict, options: Optional[dict] = None) -> list:
    '''Answer `query` (the JSON body the app posts to Druid) with a raw Druid
    response.

    Options: `empty` answers no rows; `special_values` puts NaN, infinities and
    nulls into post-aggregations; `extra_fields` adds field ids to the deployment's
    own (the e2e stack's Data Catalog has an indicator harmony_demo lacks);
    `dense` reports every aggregator whose filter matches, so no bucket is empty
    by chance.'''
    options = options or {}
    if options.get('empty'):
        return []
    rng = random.Random(_seed(case_name, query))
    metrics = _Metrics(
        query, rng, bool(options.get('special_values')), bool(options.get('dense'))
    )
    granularity = query['granularity']
    if not isinstance(granularity, str):
        raise NotImplementedError(f'synth cannot bucket granularity {granularity!r}')
    granularity = None if granularity == 'all' else granularity
    days = list(_days(query['intervals']))
    facts = [
        f
        for f in _facts(options.get('extra_fields', ()))
        if _matches(query.get('filter'), f)
    ]
    if not facts:
        return []

    if query['queryType'] == 'timeseries':
        buckets = (
            sorted({_floor(d, granularity) for d in days})
            if granularity
            else [_parse_interval(query['intervals'][0])[0]]
        )
        return [
            {
                'timestamp': _timestamp_iso(bucket),
                'result': dict(zip(metrics.names, metrics.row(facts))),
            }
            for bucket in buckets
            if not granularity or rng.random() >= 0.15
        ]

    if query['queryType'] != 'groupBy' or not query['context'].get('resultAsArray'):
        raise NotImplementedError('synth answers timeseries and resultAsArray groupBy')

    dimensions = query['dimensions']
    names = [_dimension_name(d) for d in dimensions]
    data_dimensions = [d for d in dimensions if not _is_time_dimension(d)]
    time_dimensions = [d for d in dimensions if _is_time_dimension(d)]

    facts_by_group: Dict[Tuple, List[Fact]] = {}
    for fact in facts:
        group = tuple(fact[d] for d in data_dimensions)
        facts_by_group.setdefault(group, []).append(fact)
    data_groups = sorted(facts_by_group, key=_sort_key)
    time_groups = sorted(
        {
            (
                _floor(day, granularity) if granularity else None,
                tuple(_time_dimension_value(d, day) for d in time_dimensions),
            )
            for day in days
        },
        key=lambda t: (t[0] or date.min, t[1]),
    )

    # Real data is sparse in time: most (day, location) pairs have no report. Keep
    # about DETAIL_ROW_BUDGET rows however wide the query is. Without a time axis
    # every group that passes the filter has data.
    combinations = len(time_groups) * len(data_groups)
    keep = min(0.8, DETAIL_ROW_BUDGET / combinations)
    if not granularity and not time_dimensions:
        keep = 1
    detail = [
        (bucket, time_values, data_values)
        for (bucket, time_values), data_values in product(time_groups, data_groups)
        if rng.random() < keep
    ] or [(*time_groups[0], data_groups[0])]

    def row_values(time_values: Tuple, data_values: Tuple) -> Dict[str, Any]:
        time_iter, data_iter = iter(time_values), iter(data_values)
        return {
            name: next(time_iter) if _is_time_dimension(spec) else next(data_iter)
            for name, spec in zip(names, dimensions)
        }

    rows: List[list] = []
    for block in query.get('subtotalsSpec') or [names]:
        block_facts: Dict[Tuple, List[Fact]] = {}
        for bucket, time_values, data_values in detail:
            values = row_values(time_values, data_values)
            key = (bucket, tuple(values[n] if n in block else None for n in names))
            block_facts.setdefault(key, []).extend(facts_by_group[data_values])
        for bucket, values in sorted(
            block_facts, key=lambda k: (k[0] or date.min, _sort_key(k[1]))
        ):
            row: List[Any] = [_timestamp_ms(bucket)] if granularity else []
            row.extend(values)
            row.extend(metrics.row(block_facts[(bucket, values)]))
            rows.append(row)
    if len(rows) > MAX_ROWS:
        raise ValueError(
            f'{case_name}: {len(rows)} synthetic rows; narrow its interval or groups'
        )
    return rows
