'''Deterministic stand-in for a Druid broker, used only when recording fixtures.

Given the exact native query the app posts, it answers with rows shaped the way
Druid 0.23 answers: array rows for groupBy (`resultAsArray`), `{timestamp, result}`
objects for timeseries, subtotal blocks in `subtotalsSpec` order, each block sorted
by time then dimension values with nulls first. Dimension values come from a small
sample of the `harmony_demo` data (Brazilian states and municipalities, the yellow
fever dimensions) and respect the query filter, so a policy or a filter visibly
narrows the rows. Metric values are pseudo-random but seeded from the case name and
the query's structure, so re-recording an unchanged query yields identical bytes.

The replay test never calls this module: it reads the frozen `druid_response.json`.
'''
import hashlib
import json
import random
import re
from datetime import date, datetime, timedelta, timezone
from itertools import product
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

MAX_ROWS = 5000
DETAIL_ROW_BUDGET = 300

# (StateName, StateID, StateLat, StateLon, MunicipalityName, MunicipalityID,
# MunicipalityLat, MunicipalityLon), from pipeline/harmony_demo/static_data. The last
# Acre row has no municipality: data reported at state level.
LOCATIONS = [
    ('Acre', '1', '-9.128693', '-71.973581', 'Rio Branco', '120040', '-9.974', '-67.8076'),
    ('Acre', '1', '-9.128693', '-71.973581', 'Cruzeiro do Sul', '120020', '-7.6307', '-72.6704'),
    ('Acre', '1', '-9.128693', '-71.973581', None, None, None, None),
    ('Pará', '14', '-3.974166', '-52.751945', 'Belém', '150140', '-1.4558', '-48.4902'),
    (
        'Pará', '14', '-3.974166', '-52.751945',
        'Conceição do Araguaia', '150270', '-8.2578', '-49.2647',
    ),
    ('Roraima', '23', '1.989233', '-61.330109', 'Alto Alegre', '140005', '2.9858', '-61.3071'),
    ('Roraima', '23', '1.989233', '-61.330109', 'Pacaraima', '140045', '4.4799', '-61.1477'),
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
DEFAULT_FIELDS = ['yellow_fever_cases']

COUNT_SUFFIX = '__count'
INT_AGGREGATORS = {'count', 'longSum', 'longMin', 'longMax', 'longFirst', 'longLast'}


def _seed(case_name: str, query: dict) -> int:
    '''Seed from the parts of the query that decide the result's shape and size, not
    from context or ordering, so adding a timeout or running sub-queries concurrently
    does not change the recorded data.'''
    structure = {
        'case': case_name,
        'queryType': query.get('queryType'),
        'dimensions': query.get('dimensions'),
        'aggregations': sorted(aggregator_name(a) for a in query.get('aggregations', [])),
        'postAggregations': sorted(
            p['name'] for p in query.get('postAggregations', [])
        ),
        'granularity': query.get('granularity'),
        'intervals': query.get('intervals'),
        'subtotalsSpec': query.get('subtotalsSpec'),
    }
    digest = hashlib.sha256(json.dumps(structure, sort_keys=True).encode()).digest()
    return int.from_bytes(digest[:8], 'big')


def _collect_field_ids(node: Any, output: set) -> None:
    if isinstance(node, dict):
        if node.get('dimension') == 'field':
            if node.get('type') == 'selector' and node.get('value'):
                output.add(node['value'])
            if node.get('type') == 'in':
                output.update(v for v in node.get('values', []) if v)
        for value in node.values():
            _collect_field_ids(value, output)
    elif isinstance(node, list):
        for value in node:
            _collect_field_ids(value, output)


def _facts(query: dict) -> List[Dict[str, Optional[str]]]:
    field_ids: set = set()
    _collect_field_ids(query, field_ids)
    fields = sorted(field_ids) or DEFAULT_FIELDS
    facts = []
    for location, sex, age, death, source, field in product(
        LOCATIONS,
        CATEGORICAL_VALUES['Sex'],
        CATEGORICAL_VALUES['Age'],
        CATEGORICAL_VALUES['Death'],
        CATEGORICAL_VALUES['source'],
        fields,
    ):
        fact = dict(zip(LOCATION_DIMENSIONS, location))
        fact.update(Sex=sex, Age=age, Death=death, source=source, field=field)
        facts.append(fact)
    return facts


def _matches(druid_filter: Optional[dict], fact: Dict[str, Optional[str]]) -> bool:
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
    if 'extractionFn' in druid_filter or druid_filter.get('dimension') == '__time':
        raise NotImplementedError(f'synth cannot evaluate filter {druid_filter}')
    value = fact.get(druid_filter.get('dimension')) if 'dimension' in druid_filter else None
    if kind == 'selector':
        expected = druid_filter.get('value')
        if expected in (None, ''):
            return value is None
        return value == expected
    if kind == 'in':
        values = druid_filter['values']
        if value is None:
            return None in values or '' in values
        return value in values
    if kind == 'regex':
        return value is not None and re.search(druid_filter['pattern'], value) is not None
    if kind == 'bound':
        if value is None:
            return False
        key: Callable[[str], Any] = (
            float if druid_filter.get('ordering') == 'numeric' else str
        )
        lower, upper = druid_filter.get('lower'), druid_filter.get('upper')
        if lower is not None:
            if druid_filter.get('lowerStrict') and not key(value) > key(lower):
                return False
            if key(value) < key(lower):
                return False
        if upper is not None:
            if druid_filter.get('upperStrict') and not key(value) < key(upper):
                return False
            if key(value) > key(upper):
                return False
        return True
    if kind == 'columnComparison':
        values = [fact.get(d) for d in druid_filter['dimensions']]
        return len(set(values)) == 1
    raise NotImplementedError(f'synth cannot evaluate filter type {kind!r}')


def _parse_interval(interval: str) -> Tuple[date, date]:
    start, end = interval.split('/')
    return (date.fromisoformat(start[:10]), date.fromisoformat(end[:10]))


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    return date(day.year + month_index // 12, month_index % 12 + 1, 1)


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


def _granularity_name(granularity: Any) -> Optional[str]:
    '''Normalise the query granularity to day/week/month/quarter/year, or None for
    `all`.'''
    if granularity in (None, 'all'):
        return None
    if isinstance(granularity, str):
        return granularity
    if granularity.get('type') == 'period':
        period = {'P1D': 'day', 'P1W': 'week', 'P1M': 'month', 'P3M': 'quarter'}
        return period.get(granularity['period']) or 'year'
    raise NotImplementedError(f'synth cannot bucket granularity {granularity!r}')


def _days(intervals: Sequence[str]) -> Iterable[date]:
    for interval in intervals:
        start, end = _parse_interval(interval)
        day = start
        while day < end:
            yield day
            day += timedelta(days=1)


def _epi_week_of_year(day: date) -> str:
    '''Mirror of WHO_EPI_WEEK_EXTRACTION_FORMULA (db/druid/js_formulas), run in UTC.'''

    def epi_year_start(year: int) -> date:
        start = date(year, 1, 4)
        return start - timedelta(days=start.weekday())

    start = epi_year_start(day.year)
    if day.month == 12 and day.day >= 29 and day >= epi_year_start(day.year + 1):
        start = epi_year_start(day.year + 1)
    epi_week = (day - start).days // 7
    output = date(2999, 12, 30) + timedelta(days=7 * epi_week)
    return f'{output.isoformat()}T00:00:00.000Z'


def _joda_format(day: date, pattern: str) -> str:
    return (
        pattern.replace('YYYY', f'{day.year:04d}')
        .replace('yyyy', f'{day.year:04d}')
        .replace('MM', f'{day.month:02d}')
        .replace('dd', f'{day.day:02d}')
    )


def _time_dimension_value(spec: dict, day: date) -> str:
    extraction = spec['extractionFn']
    if extraction['type'] == 'timeFormat':
        granularity = extraction.get('granularity')
        bucket = _floor(day, granularity) if granularity else day
        return _joda_format(bucket, extraction['format'])
    if extraction['type'] == 'javascript' and 'epiWeekOfYear' in extraction['function']:
        return _epi_week_of_year(day)
    raise NotImplementedError(f'synth cannot evaluate extraction {extraction}')


def _dimension_name(spec: Any) -> str:
    return spec if isinstance(spec, str) else spec['outputName']


def _is_time_dimension(spec: Any) -> bool:
    return isinstance(spec, dict) and spec.get('dimension') == '__time'


def _source_dimension(spec: Any) -> str:
    return spec if isinstance(spec, str) else spec['dimension']


def _timestamp_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()) * 1000


def _timestamp_iso(day: date) -> str:
    return f'{day.isoformat()}T00:00:00.000Z'


def _inner_aggregator(aggregator: dict) -> dict:
    while aggregator.get('type') == 'filtered':
        aggregator = aggregator['aggregator']
    return aggregator


def aggregator_name(aggregator: dict) -> str:
    return aggregator.get('name') or _inner_aggregator(aggregator)['name']


class _Metrics:
    def __init__(self, query: dict, rng: random.Random, special_values: bool):
        self.aggregations = query.get('aggregations', [])
        self.post_aggregations = query.get('postAggregations', [])
        self.rng = rng
        self.special_values = special_values

    @property
    def names(self) -> List[str]:
        return [aggregator_name(a) for a in self.aggregations] + [
            p['name'] for p in self.post_aggregations
        ]

    def _number(self) -> float:
        if self.rng.random() < 0.7:
            return float(self.rng.randint(1, 400))
        return round(self.rng.uniform(0.5, 400), 2)

    def row(self) -> List[Any]:
        empty = self.rng.random() < 0.15
        values: Dict[str, Any] = {}
        for aggregator in self.aggregations:
            name = aggregator_name(aggregator)
            kind = _inner_aggregator(aggregator).get('type', '')
            if name.endswith(COUNT_SUFFIX) or kind in INT_AGGREGATORS:
                values[name] = 0 if empty else self.rng.randint(1, 60)
            else:
                values[name] = 0.0 if empty else self._number()
        for post_aggregator in self.post_aggregations:
            name = post_aggregator['name']
            if self.special_values and self.rng.random() < 0.3:
                values[name] = self.rng.choice(['NaN', 'Infinity', '-Infinity', None])
            else:
                values[name] = 0.0 if empty else round(self.rng.uniform(0, 1000), 4)
        return [values[name] for name in self.names]


def _sort_key(values: Sequence[Optional[str]]) -> Tuple:
    return tuple((value is not None, value or '') for value in values)


def synthesize(case_name: str, query: dict, options: Optional[dict] = None) -> list:
    '''Answer `query` (the JSON body the app posts to Druid) with a raw Druid
    response.'''
    options = options or {}
    if options.get('empty'):
        return []
    rng = random.Random(_seed(case_name, query))
    metrics = _Metrics(query, rng, bool(options.get('special_values')))
    query_type = query['queryType']
    granularity = _granularity_name(query.get('granularity'))
    intervals = query['intervals']
    if isinstance(intervals, str):
        intervals = [intervals]
    days = list(_days(intervals))

    if query_type == 'timeseries':
        buckets = sorted({_floor(d, granularity) for d in days}) if granularity else [
            _parse_interval(intervals[0])[0]
        ]
        rows = []
        for bucket in buckets:
            if granularity and rng.random() < 0.15:
                continue
            rows.append(
                {
                    'timestamp': _timestamp_iso(bucket),
                    'result': dict(zip(metrics.names, metrics.row())),
                }
            )
        return rows

    if query_type != 'groupBy':
        raise NotImplementedError(f'synth cannot answer queryType {query_type!r}')
    if not query.get('context', {}).get('resultAsArray'):
        raise NotImplementedError('synth only answers resultAsArray groupBy queries')

    dimensions = query.get('dimensions', [])
    names = [_dimension_name(d) for d in dimensions]
    data_dimensions = [d for d in dimensions if not _is_time_dimension(d)]
    time_dimensions = [d for d in dimensions if _is_time_dimension(d)]

    facts = [f for f in _facts(query) if _matches(query.get('filter'), f)]
    data_groups = sorted(
        {tuple(f.get(_source_dimension(d)) for d in data_dimensions) for f in facts},
        key=_sort_key,
    )
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
    keep = min(0.8, DETAIL_ROW_BUDGET / combinations) if combinations else 0
    if not granularity and not time_dimensions:
        keep = 1
    detail = []
    for (bucket, time_values), data_values in product(time_groups, data_groups):
        if rng.random() >= keep:
            continue
        data_iter = iter(data_values)
        time_iter = iter(time_values)
        values = {
            name: next(time_iter) if _is_time_dimension(spec) else next(data_iter)
            for name, spec in zip(names, dimensions)
        }
        detail.append((bucket, values))
    if not detail and data_groups and time_groups:
        bucket, time_values = time_groups[0]
        time_iter = iter(time_values)
        data_iter = iter(data_groups[0])
        detail.append(
            (
                bucket,
                {
                    name: next(time_iter) if _is_time_dimension(spec) else next(data_iter)
                    for name, spec in zip(names, dimensions)
                },
            )
        )

    blocks = query.get('subtotalsSpec') or [names]
    rows: List[list] = []
    for block in blocks:
        keys = sorted(
            {
                (bucket, tuple(values[n] if n in block else None for n in names))
                for bucket, values in detail
            },
            key=lambda k: (k[0] or date.min, _sort_key(k[1])),
        )
        for bucket, values in keys:
            row: List[Any] = [_timestamp_ms(bucket)] if granularity else []
            row.extend(values)
            row.extend(metrics.row())
            rows.append(row)
    if len(rows) > MAX_ROWS:
        raise ValueError(
            f'{case_name}: {len(rows)} synthetic rows; narrow the case interval or groups'
        )
    return rows
