'''Offline harness for the golden query suite.

A case is a directory under `cases/` holding:
- `case.json`: the endpoint, the caller's query policy, and recording options;
- `request.json`: the body the frontend posts to `/api2/query/<endpoint>`;
- `druid_query.json`: every native query the app posts to Druid, in issue order;
- `druid_response.json`: the raw Druid answer to each of those queries;
- `expected_response.json`: the body the endpoint returns.

A case is replayed through the real `/api2/query` Potion routes on a bare Flask app
that carries the harmony_demo config: request validation and conversion, query
building, the query-policy filter (`AuthorizedQueryClient`), the Druid client's
parsing, and shaping all run as in production. Only the HTTP call to the Druid
broker (`DruidQueryClient_.run_raw_query`) is replaced; it answers from
`druid_response.json`.
'''
import importlib
import io
import json
import os
import pkgutil
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator, List, Optional, Tuple
from unittest import mock

CASES_DIR = Path(__file__).parent / 'cases'

DEPLOYMENT = 'harmony_demo'
DATASOURCE_DATE = datetime(2026, 1, 1)
DATA_MIN_TIME = '2018-01-01T00:00:00'
DATA_MAX_TIME = '2026-01-01T00:00:00'
FROZEN_NOW = '2026-01-15 12:00:00'

# Sketch sizes the dimension metadata would compute for the demo datasource. They
# only feed COUNT_DISTINCT aggregators and the grouped-sketch optimisation.
SKETCH_SIZES = {
    'StateID': 64,
    'MunicipalityID': 8192,
    'Sex': 16,
    'Age': 16,
    'Death': 16,
    'source': 16,
}
GROUPED_SKETCH_SIZES = {'StateName': {'MunicipalityID': 1024}}

_APP = None


def bootstrap():
    '''Build the bare Flask app once and leave its app context pushed. Several
    query modules read `current_app` at import time, so this runs before any of
    them is imported.'''
    global _APP  # pylint: disable=global-statement
    if _APP is not None:
        return _APP
    if os.environ.get('ZEN_PROD'):
        raise RuntimeError('Unset ZEN_PROD: log config would write to /data/output')
    os.environ.setdefault('ZEN_ENV', DEPLOYMENT)
    os.environ.setdefault('DRUID_HOST', 'http://druid.golden.invalid')
    os.environ.setdefault('DEFAULT_SECRET_KEY', 'golden-suite-not-a-secret')

    # pylint: disable=import-outside-toplevel
    from flask import Flask
    from flask_potion import Api

    from config.loader import import_configuration_module
    from data.query.mock import generate_web_query_mock_data
    from db.druid.datasource import SiteDruidDatasource
    from web.server.data.time_boundary import DataTimeBoundary

    datasource = SiteDruidDatasource(DEPLOYMENT, DATASOURCE_DATE)
    app = Flask('golden')
    app.zen_config = import_configuration_module(DEPLOYMENT)
    app.druid_context = SimpleNamespace(
        current_datasource=datasource,
        data_time_boundary=DataTimeBoundary(
            None,
            datasource,
            {
                'timestamp': '',
                'result': {'minTime': DATA_MIN_TIME, 'maxTime': DATA_MAX_TIME},
            },
        ),
        dimension_metadata=SimpleNamespace(
            sketch_sizes=SKETCH_SIZES,
            grouped_dimension_sketch_sizes=GROUPED_SKETCH_SIZES,
        ),
    )
    app.query_data = generate_web_query_mock_data(
        app.zen_config.aggregation.CALENDAR_SETTINGS
    )
    app.app_context().push()

    # Potion resources configure every SQLAlchemy mapper, so every model module
    # must be registered first, as importing the full web app would do.
    import models.alchemy

    for module in pkgutil.walk_packages(models.alchemy.__path__, 'models.alchemy.'):
        importlib.import_module(module.name)

    from web.server.api.query.api_models import GranularityResource
    from web.server.api.query.query_models import QueryResource

    GranularityResource.init()
    Api(app, prefix='/api2').add_resource(QueryResource)
    _APP = app
    return app


_ALTERNATION = re.compile(r'^\((.*)\)$')


def _canonical_regex(pattern: str) -> str:
    '''`build_query_filter_from_aggregations` joins a set of patterns as
    `(a)|(b)`; sort the alternatives.'''
    match = _ALTERNATION.match(pattern)
    if not match:
        return pattern
    parts = match.group(1).split(')|(')
    if any(part.count('(') != part.count(')') for part in parts):
        return pattern
    return '(' + ')|('.join(sorted(parts)) + ')'


def _canonical(node: Any) -> Any:
    if isinstance(node, list):
        return [_canonical(item) for item in node]
    if not isinstance(node, dict):
        return node
    output = {key: _canonical(value) for key, value in node.items()}
    kind = output.get('type')
    if kind in ('and', 'or'):
        for operands in ('fields', 'havingSpecs'):
            if isinstance(output.get(operands), list):
                output[operands] = sorted(output[operands], key=dumps_compact)
    elif kind == 'in' and isinstance(output.get('values'), list):
        output['values'] = sorted(output['values'], key=dumps_compact)
    elif kind == 'regex' and isinstance(output.get('pattern'), str):
        output['pattern'] = _canonical_regex(output['pattern'])
    return output


def canonical_query(query: dict) -> dict:
    '''The posted query with set-ordered parts sorted.

    The query builder and the policy filter build several lists from Python sets,
    so their order follows PYTHONHASHSEED: `and`/`or` filter and having operands,
    `in` values, regex alternatives and the aggregator list. Druid treats each of these as unordered;
    the aggregator order only fixes the column order of array result rows, which
    `CannedDruidClient` maps by name. Nothing else is reordered.'''
    output = _canonical(json.loads(json.dumps(query)))
    if isinstance(output.get('aggregations'), list):
        output['aggregations'] = sorted(output['aggregations'], key=_aggregator_name)
    return output


def _aggregator_name(aggregator: dict) -> str:
    while 'name' not in aggregator and 'aggregator' in aggregator:
        aggregator = aggregator['aggregator']
    return aggregator['name']


def _array_header(query: dict) -> List[str]:
    '''Column names of a `resultAsArray` groupBy row, as `GroupByQueryBuilder.parse`
    expects them.'''
    header = ['__timestamp'] if query.get('granularity') != 'all' else []
    header += [d if isinstance(d, str) else d['outputName'] for d in query['dimensions']]
    header += [_aggregator_name(a) for a in query.get('aggregations', [])]
    header += [p['name'] for p in query.get('postAggregations', [])]
    if len(set(header)) != len(header):
        raise ValueError(f'Duplicate result column names: {header}')
    return header


def dumps_compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=True)


def to_json_text(value: Any) -> str:
    '''The one serialisation used for every fixture file and every comparison.
    Floats keep their full repr; NaN and Infinity are written as bare tokens, as
    Python's json module and Flask emit them.'''
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=True)
        + '\n'
    )


class CannedDruidClient:
    '''Builds a `DruidQueryClient_` whose broker is a function of the canonical
    query. Built lazily because the real class reads settings at import time.'''

    @staticmethod
    def create(answer: Callable[[dict], list]):
        # pylint: disable=import-outside-toplevel
        import ijson

        from db.druid.query_client import DruidQueryClient_

        class _Client(DruidQueryClient_):
            def __init__(self):  # pylint: disable=super-init-not-called
                self.exchanges: List[Tuple[dict, list]] = []

            def run_raw_query(self, query, streaming=False):
                posted = canonical_query(query)
                response = answer(posted)
                self.exchanges.append((posted, response))
                if response and isinstance(response[0], list):
                    positions = [
                        _array_header(posted).index(name)
                        for name in _array_header(query)
                    ]
                    response = [[row[i] for i in positions] for row in response]
                payload = json.dumps(response).encode()
                if streaming:
                    return ijson.items(io.BytesIO(payload), 'item', use_float=True)
                return json.loads(payload)

        return _Client()


@dataclass
class Case:
    name: str
    path: Path

    def read(self, filename: str) -> Any:
        with open(self.path / filename, encoding='utf-8') as handle:
            return json.load(handle)

    def write(self, filename: str, value: Any) -> None:
        with open(self.path / filename, 'w', encoding='utf-8') as handle:
            handle.write(to_json_text(value))

    @property
    def meta(self) -> dict:
        return self.read('case.json')


def load_cases() -> List[Case]:
    return [
        Case(path.name, path)
        for path in sorted(CASES_DIR.iterdir())
        if (path / 'case.json').exists()
    ]


def _identity(policy: Optional[dict]):
    '''Build the Flask-Principal identity the request would carry.

    `policy` null means a site administrator, who is never filtered. Otherwise
    `query_policies` lists `QueryPolicy` rows as stored (`dimension`,
    `dimension_value`, null meaning all values), and `query_needs` lists
    multi-dimension needs as a JWT `query_needs` claim grants them.'''
    # pylint: disable=import-outside-toplevel
    from flask_principal import Identity, RoleNeed

    from models.alchemy.query_policy.model import QueryPolicy
    from models.python.permissions import DimensionFilter, QueryNeed
    from web.server.routes.views.query_policy import construct_query_need_from_policy

    identity = Identity('golden-user')
    if policy is None:
        identity.provides.add(RoleNeed('admin'))
        return identity
    for row in policy.get('query_policies', []):
        identity.provides.add(
            construct_query_need_from_policy(
                QueryPolicy(
                    dimension=row['dimension'], dimension_value=row['dimension_value']
                )
            )
        )
    for need in policy.get('query_needs', []):
        identity.provides.add(
            QueryNeed(
                [
                    DimensionFilter(
                        dimension,
                        spec.get('include_values'),
                        spec.get('exclude_values'),
                        spec.get('all_values', False),
                    )
                    for dimension, spec in need.items()
                ]
            )
        )
    return identity


@contextmanager
def _caller(app, policy: Optional[dict], raw_client) -> Iterator[None]:
    # pylint: disable=import-outside-toplevel
    from flask import g

    from web.server.routes.views import query_policy

    app.query_client = query_policy.AuthorizedQueryClient(raw_client)
    g.identity = _identity(policy)
    # `is_public_dashboard_user` reads the public-access setting from Postgres. The
    # golden cases run with public access off, as harmony_demo ships.
    with mock.patch.object(query_policy, 'is_public_dashboard_user', lambda: False):
        try:
            yield
        finally:
            del g.identity
            del app.query_client


def run_case(case: Case, answer: Callable[[dict], list]) -> Tuple[List[Tuple[dict, list]], Any]:
    '''POST the case's request and return the Druid exchanges and the parsed body.'''
    # pylint: disable=import-outside-toplevel
    from freezegun import freeze_time

    app = bootstrap()
    meta = case.meta
    raw_client = CannedDruidClient.create(answer)
    with freeze_time(FROZEN_NOW), _caller(app, meta.get('policy'), raw_client):
        response = app.test_client().post(
            f"/api2/query/{meta['endpoint']}",
            data=json.dumps(case.read('request.json')),
            content_type='application/json',
        )
    body = response.get_data(as_text=True)
    if response.status_code != 200:
        raise AssertionError(f'{case.name}: HTTP {response.status_code}\n{body[:2000]}')
    return raw_client.exchanges, json.loads(body)


class RecordedDruid:
    '''Answers each posted query from the recording: the unused recorded query that
    is identical, else the one at the same position, else an empty result. Matching
    on content keeps replay valid when independent sub-queries run concurrently;
    the positional fallback lets a changed query still produce a response diff.'''

    def __init__(self, queries: List[dict], responses: List[list]):
        if len(queries) != len(responses):
            raise ValueError('druid_query.json and druid_response.json differ in length')
        self._recorded = list(zip(queries, responses))
        self._used: set = set()
        self._calls = 0

    def __call__(self, posted: dict) -> list:
        position = self._calls
        self._calls += 1
        posted_text = dumps_compact(posted)
        for index, (query, response) in enumerate(self._recorded):
            if index not in self._used and dumps_compact(query) == posted_text:
                self._used.add(index)
                return response
        if position < len(self._recorded):
            return self._recorded[position][1]
        return []
