'''Offline harness for the golden query suite.

A case is a directory under `cases/` holding:
- `case.json`: the endpoint, the caller's query policy, and recording options;
- `request.json`: the body the frontend posts to `/api2/query/<endpoint>`;
- `druid_query.json`: every native query the app posts to Druid, in issue order;
- `druid_response.json`: the raw Druid answer to each of those queries;
- `expected_response.json`: the body the endpoint returns.

A case is POSTed through the real `/api2/query` Potion routes on a bare Flask app
that carries the harmony_demo config. Request validation and conversion, query
building, the query-policy filter (`AuthorizedQueryClient`), the production
`DruidQueryClient_` (request serialisation, status handling, gzip decoding,
streamed JSON decoding with `db.druid.json_stream`, parsing) and shaping all run
as in production. The broker is replaced at the transport: a requests adapter
mounted on the client's pooled session answers each POST from
`druid_response.json`.

The rest of the environment is fixed here, and nothing else is patched:
- `app.druid_context` is a stub with a fixed datasource, data time boundary and
  sketch sizes (the real one reads Postgres and Druid);
- the clock is frozen at FROZEN_NOW (freezegun);
- `query_policy.is_public_dashboard_user` returns False (the real one reads the
  public-access setting from Postgres), so the anonymous public-dashboard branch,
  which skips the policy, is not exercised.
'''

import gzip
import importlib
import json
import os
import pkgutil
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator, List, Optional, Tuple
from unittest import mock

CASES_DIR = Path(__file__).parent / 'cases'

DEPLOYMENT = 'harmony_demo'
DRUID_HOST = 'http://druid.golden.invalid'
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
    os.environ.setdefault('DRUID_HOST', DRUID_HOST)
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
    return output


def canonical_query(query: dict) -> dict:
    '''The posted query with set-ordered parts sorted.

    The query builder and the policy filter build several lists from Python sets,
    so their order follows PYTHONHASHSEED: `and`/`or` filter and having operands,
    `in` values and the aggregator list. Druid treats each of these as unordered;
    the aggregator order only fixes the column order of array result rows, which
    the transport maps by name. Nothing else is reordered.'''
    output = _canonical(query)
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
    header += [
        d if isinstance(d, str) else d['outputName'] for d in query['dimensions']
    ]
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


def _broker_adapter(answer: Callable[[dict], list], exchanges: list):
    '''A requests transport adapter standing in for the Druid broker.

    It receives the bytes `DruidQueryClient_` serialised, answers the canonical
    query with `answer`, puts the result columns back in the order the app asked
    for, and replies 200 with a JSON body, gzip-encoded when the client asked for
    gzip on a streamed request (the client decodes those itself).'''
    # pylint: disable=import-outside-toplevel
    from requests.adapters import BaseAdapter
    from requests.models import Response
    from requests.structures import CaseInsensitiveDict

    class BrokerAdapter(BaseAdapter):
        def send(self, request, stream=False, **kwargs):  # pylint: disable=arguments-differ
            asked = json.loads(request.body)
            posted = canonical_query(asked)
            rows = answer(posted)
            exchanges.append((posted, rows))
            if rows and isinstance(rows[0], list):
                positions = [
                    _array_header(posted).index(name) for name in _array_header(asked)
                ]
                rows = [[row[i] for i in positions] for row in rows]
            body = json.dumps(rows).encode()
            headers = {'Content-Type': 'application/json'}
            if stream and 'gzip' in request.headers.get('Accept-Encoding', ''):
                body = gzip.compress(body)
                headers['Content-Encoding'] = 'gzip'
            response = Response()
            response.status_code = 200
            response.headers = CaseInsensitiveDict(headers)
            response.raw = BytesIO(body)
            response.url = request.url
            response.request = request
            response.encoding = 'utf-8'
            return response

        def close(self):
            pass

    return BrokerAdapter()


@contextmanager
def _druid_client(answer: Callable[[dict], list]) -> Iterator[Tuple[Any, list]]:
    '''The production `DruidQueryClient_`, its pooled session's transport swapped
    for the broker adapter for the duration of one case.'''
    # pylint: disable=import-outside-toplevel
    from db.druid.config import construct_druid_configuration
    from db.druid.query_client import DruidQueryClient_, _get_session

    configuration = construct_druid_configuration(DRUID_HOST)
    session = _get_session(configuration)
    prefix = configuration.query_endpoint()
    original = session.adapters[prefix]
    exchanges: list = []
    session.mount(prefix, _broker_adapter(answer, exchanges))
    try:
        yield DruidQueryClient_(configuration), exchanges
    finally:
        session.mount(prefix, original)


@dataclass
class Case:
    name: str
    path: Path

    def read(self, filename: str) -> Any:
        with open(self.path / filename, encoding='utf-8') as handle:
            return json.load(handle)

    @property
    def meta(self) -> dict:
        return self.read('case.json')


def load_cases() -> List[Case]:
    return [
        Case(path.name, path) for path in sorted(CASES_DIR.iterdir()) if path.is_dir()
    ]


def _account_identity(policy: dict):
    # pylint: disable=import-outside-toplevel
    from flask_principal import Identity

    from models.alchemy.query_policy.model import QueryPolicy
    from web.server.routes.views.query_policy import construct_query_need_from_policy

    identity = Identity('golden-user')
    for row in policy.get('query_policies', []):
        identity.provides.add(
            construct_query_need_from_policy(
                QueryPolicy(
                    dimension=row['dimension'], dimension_value=row['dimension_value']
                )
            )
        )
    return identity


@contextmanager
def _caller(app, policy: Optional[dict], raw_client) -> Iterator[None]:
    '''Install the identity the request would carry.

    `policy` null is a site administrator, who is never filtered. Otherwise
    `query_policies` lists the account's `QueryPolicy` rows as stored (`dimension`,
    `dimension_value`, null meaning all values). `jwt_query_needs`, when present,
    is the `query_needs` claim of a JWT the account signed in with; the identity's
    needs are then replaced as `signal_handlers._install_token_needs` does.'''
    # pylint: disable=import-outside-toplevel
    from flask import g
    from flask_principal import Identity, RoleNeed

    from web.server.routes.views import query_policy
    from web.server.security.signal_handlers import _compute_token_provides

    app.query_client = query_policy.AuthorizedQueryClient(raw_client)
    if policy is None:
        g.identity = Identity('golden-admin')
        g.identity.provides.add(RoleNeed('admin'))
    else:
        g.identity = _account_identity(policy)
        if 'jwt_query_needs' in policy:
            g.identity.provides = _compute_token_provides(
                {'query_needs': policy['jwt_query_needs']}
            )
    with mock.patch.object(query_policy, 'is_public_dashboard_user', lambda: False):
        try:
            yield
        finally:
            del g.identity
            del app.query_client


_CASE_POLICY = object()


def run_case(
    case: Case,
    answer: Callable[[dict], list],
    policy: Any = _CASE_POLICY,
) -> Tuple[List[Tuple[dict, list]], Any]:
    '''POST the case's request and return the Druid exchanges and the parsed body.
    `policy` overrides the caller described in case.json.'''
    # pylint: disable=import-outside-toplevel
    from freezegun import freeze_time

    app = bootstrap()
    meta = case.meta
    if policy is _CASE_POLICY:
        policy = meta.get('policy')
    with ExitStack() as stack:
        stack.enter_context(freeze_time(FROZEN_NOW))
        raw_client, exchanges = stack.enter_context(_druid_client(answer))
        stack.enter_context(_caller(app, policy, raw_client))
        response = app.test_client().post(
            f"/api2/query/{meta['endpoint']}",
            data=json.dumps(case.read('request.json')),
            content_type='application/json',
        )
    body = response.get_data(as_text=True)
    if response.status_code != 200:
        raise AssertionError(f'{case.name}: HTTP {response.status_code}\n{body[:2000]}')
    return exchanges, json.loads(body)


class RecordedDruid:
    '''Answers each posted query from the recording: the unused recorded query that
    is identical, else the one at the same position, else an empty result. Matching
    on content keeps replay valid when independent sub-queries run concurrently;
    the positional fallback lets a changed query still produce a response diff.'''

    def __init__(self, queries: List[dict], responses: List[list]):
        if len(queries) != len(responses):
            raise ValueError(
                'druid_query.json and druid_response.json differ in length'
            )
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
