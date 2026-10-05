'''Query shaping steps that pandas 2.2 broke (WP-3b, INV-2).

Each expected value is what the pre-WP-3b code returned on pandas 1.5.3.
'''

import math
from types import SimpleNamespace

import pandas as pd
import pytest

from data.query.models import GroupingDimension
from web.server.query.request import SUBTOTAL_RESULT_LABEL
from web.server.query.visualizations.base import QueryBase
from web.server.query.visualizations.hierarchy import HierarchyVisualization
from web.server.query.visualizations.map import build_map_response

CASES = [SimpleNamespace(id='cases')]


@pytest.fixture(name='app_context')
def fixture_app_context(bare_flask_app):
    # The data quality modules read GEO_FIELD_ORDERING from the app at import.
    app = bare_flask_app()
    app.zen_config = SimpleNamespace(
        aggregation=SimpleNamespace(
            GEO_FIELD_ORDERING=['StateName', 'MunicipalityName']
        )
    )
    with app.app_context():
        yield


def test_map_rows_become_data_points_with_native_values():
    # pandas 2 no longer builds `to_dict('records', into)` rows through `into`.
    df = pd.DataFrame(
        {
            'MunicipalityName': ['Rio Branco', 'Belém', 'Boa Vista'],
            'lat': ['-9.97', '0.0', None],
            'lng': [-67.81, -48.5, 0.0],
            'cases': [12.0, float('nan'), 3.5],
            'deaths': [1, 2, 3],
        }
    )

    data = build_map_response(
        df, ['MunicipalityName'], ['cases', 'deaths'], ['lat', 'lng']
    )['data']

    assert [point['dimensions'] for point in data] == [
        {'MunicipalityName': 'Rio Branco'},
        {'MunicipalityName': 'Belém'},
        {'MunicipalityName': 'Boa Vista'},
    ]
    assert [(point['lat'], point['lng']) for point in data] == [
        ('-9.97', -67.81),
        (0, -48.5),
        (0, 0),
    ]
    assert data[0]['metrics'] == {'cases': 12.0, 'deaths': 1}
    assert math.isnan(data[1]['metrics']['cases'])
    assert data[2]['metrics'] == {'cases': 3.5, 'deaths': 3}
    assert {type(point['metrics']['deaths']) for point in data} == {int}
    assert {type(point['metrics']['cases']) for point in data} == {float}


def test_hierarchy_keeps_child_order():
    # pandas 2 takes no positional `axis` in `DataFrame.drop`.
    hierarchy = HierarchyVisualization.__new__(HierarchyVisualization)
    QueryBase.__init__(
        hierarchy,
        SimpleNamespace(
            fields=CASES,
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

    response = hierarchy.build_response(hierarchy.build_df(raw))

    root = response['root']
    assert response['levels'] == ['StateName']
    assert (root['name'], root['dimension'], root['metrics']) == (
        'Overall',
        '',
        {'cases': 8.0},
    )
    assert [(child['name'], child['dimension']) for child in root['children']] == [
        ('Pará', 'StateName'),
        ('Acre', 'StateName'),
        ('Roraima', 'StateName'),
    ]
    assert [child['metrics']['cases'] for child in root['children']][:2] == [5.0, 3.0]
    assert math.isnan(root['children'][2]['metrics']['cases'])


@pytest.mark.usefixtures('app_context')
def test_box_plot_outlier_percentages():
    # pandas 2 removed `Series.iteritems`.
    # pylint: disable=import-outside-toplevel
    from web.server.query.data_quality.outliers_box_plot import OutliersBoxPlot

    box_plot = OutliersBoxPlot(
        SimpleNamespace(
            fields=CASES,
            grouping_dimensions=lambda: [SimpleNamespace(dimension='StateName')],
        ),
        None,
        None,
        'All',
    )
    box_plot.lowest_granularity_geo = 'MunicipalityName'
    rows = [
        ('Acre, Rio Branco', 'Acre', 'Rio Branco', value)
        for value in [10.0, 11.0, 9.0, 10.0, 10.0, 11.0, 9.0, 10.0, 60.0, 10.0]
    ] + [('Pará, Belém', 'Pará', 'Belém', value) for value in [3.0, 4.0, None, 5.0]]
    df = pd.DataFrame(rows, columns=['key', 'StateName', 'MunicipalityName', 'cases'])

    assert box_plot.build_response(df) == {
        'data': [
            {
                'dimensions': {'StateName': 'Pará', 'MunicipalityName': 'Belém'},
                'metrics': {'cases': 0.0},
            },
            {
                'dimensions': {'StateName': 'Acre', 'MunicipalityName': 'Rio Branco'},
                'metrics': {'cases': 10.0},
            },
        ],
        'dimensions': ['StateName', 'MunicipalityName'],
    }


@pytest.mark.usefixtures('app_context')
def test_druid_timestamps_parse_as_utc():
    # pandas 2 applies `format='%Y-%m-%d'` strictly; pandas 1.5 parsed the whole
    # ISO 8601 timestamp.
    # pylint: disable=import-outside-toplevel
    from web.server.query.data_quality.data_quality_report import (
        parse_druid_timestamps,
    )

    parsed = parse_druid_timestamps(
        pd.Series(['2024-01-01T00:00:00.000Z', None, '2023-12-31T00:00:00.000Z'])
    )

    assert str(parsed.dtype) == 'datetime64[ns, UTC]'
    assert list(parsed) == [
        pd.Timestamp('2024-01-01', tz='UTC'),
        pd.NaT,
        pd.Timestamp('2023-12-31', tz='UTC'),
    ]
