'''Run each shaping scenario through the code in <tree> and print the results, so
the unit tests can pin the pandas 1.5 (pre-WP-3b) output.

    uv run --project <tree> python /tmp/core3b/capture.py <tree>
'''

import os
import sys
from types import SimpleNamespace

root = os.path.abspath(sys.argv[1])
os.chdir(root)
sys.path.insert(0, root)
from tests.golden.harness import bootstrap  # noqa: E402

bootstrap()

import pandas as pd  # noqa: E402
from pydruid.query import Query  # noqa: E402

from data.query.models import GroupingDimension  # noqa: E402
from db.druid.query_builder import PydruidQueryWrapper  # noqa: E402
from web.server.query.data_quality.outliers_box_plot import OutliersBoxPlot  # noqa: E402
from web.server.query.request import SUBTOTAL_RESULT_LABEL  # noqa: E402
from web.server.query.visualizations.base import QueryBase  # noqa: E402
from web.server.query.visualizations.hierarchy import HierarchyVisualization  # noqa: E402
from web.server.query.visualizations.map import build_map_response  # noqa: E402

print('pandas', pd.__version__)

# A. outer merge order
left = pd.DataFrame(
    {
        'region': ['b', 'a', 'b', None, 'b'],
        'timestamp': ['t2', 't1', 't1', 't1', 't2'],
        'val': [1, 2, 3, 4, 5],
    }
)
right = pd.DataFrame(
    [(r, t) for r in ['b', 'a', None, 'c'] for t in ['t1', 't2', 't3']],
    columns=['region', 'timestamp'],
)
merged = left.merge(right, how='outer', sort=False)
print('A', merged.astype(object).where(merged.notna(), None).values.tolist())


# B. export_pandas date filling
def event(ts, state, val):
    return {'event': {'timestamp': ts, 'StateName': state, 'cases': val}}


query = PydruidQueryWrapper(
    Query({'granularity': 'month', 'dimensions': ['StateName']}, 'groupBy')
)
query.result = [
    event('2024-01-01T00:00:00.000Z', 'Pará', 1.0),
    event('2024-01-01T00:00:00.000Z', 'Acre', 2.0),
    event('2024-02-01T00:00:00.000Z', 'Pará', 3.0),
    event('2024-03-01T00:00:00.000Z', 'Acre', 4.0),
]
filled = query.export_pandas(fill_intermediate_dates=True)
print(
    'B',
    list(filled.columns),
    filled.astype(object).where(filled.notna(), None).values.tolist(),
    list(filled.index),
)

# C. map records
map_df = pd.DataFrame(
    {
        'MunicipalityName': ['Rio Branco', 'Belém', 'Boa Vista'],
        'lat': ['-9.97', '0.0', None],
        'lng': [-67.81, -48.5, 0.0],
        'cases': [12.0, float('nan'), 3.5],
        'deaths': [1, 2, 3],
    }
)
print(
    'C',
    build_map_response(
        map_df, ['MunicipalityName'], ['cases', 'deaths'], ['lat', 'lng']
    ),
)

# D. hierarchy
fields = [SimpleNamespace(id='cases')]
hierarchy = HierarchyVisualization.__new__(HierarchyVisualization)
QueryBase.__init__(
    hierarchy,
    SimpleNamespace(
        fields=fields,
        groups=[GroupingDimension('StateName', False, False, include_total=True)],
    ),
    None,
    None,
)
raw = pd.DataFrame(
    {
        'StateName': ['Pará', 'Acre', 'Roraima', SUBTOTAL_RESULT_LABEL],
        'cases': [5.0, 3.0, float('nan'), 8.0],
    }
)
print('D', hierarchy.build_response(hierarchy.build_df(raw)))

# E. box plot
box = OutliersBoxPlot(
    SimpleNamespace(
        fields=fields,
        grouping_dimensions=lambda: [SimpleNamespace(dimension='StateName')],
    ),
    None,
    None,
    'All',
)
box.lowest_granularity_geo = 'MunicipalityName'
values = [10.0, 11.0, 9.0, 10.0, 10.0, 11.0, 9.0, 10.0, 60.0, 10.0]
rows = [('Acre, Rio Branco', 'Acre', 'Rio Branco', v) for v in values]
rows += [('Pará, Belém', 'Pará', 'Belém', v) for v in [3.0, 4.0, None, 5.0]]
box_df = pd.DataFrame(rows, columns=['key', 'StateName', 'MunicipalityName', 'cases'])
print('E', box.build_response(box_df))

# F. data quality timestamps
stamps = pd.Series(['2024-01-01T00:00:00.000Z', None, '2023-12-31T00:00:00.000Z'])
try:
    from web.server.query.data_quality.data_quality_report import parse_druid_timestamps

    parsed = parse_druid_timestamps(stamps)
except ImportError:
    parsed = pd.to_datetime(stamps, format='%Y-%m-%d')
print('F', parsed.dtype, list(parsed))
