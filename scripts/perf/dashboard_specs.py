"""Writes scripts/perf/dashboards.json: the reference dashboards dashboards.mjs loads.

Runs inside the perf stack's web container, where the dashboard models import:

    docker compose -p harmony-wp1a-perf-web exec -T web \\
        python scripts/perf/dashboard_specs.py > scripts/perf/dashboards.json

Each tile below is a compact definition. The script builds the frontend's query
selections from it and fills every other setting with the defaults of the
latest dashboard model (models/python/dashboard/latest), because the frontend
deserialiser needs the full specification and create stores it unchanged.
There is no date filter, so every tile reads the whole dataset.
"""

import json
import sys

import related

from models.python.dashboard.latest.model import DashboardSpecification
from models.python.dashboard.version import LATEST_VERSION

FIELDS = {
    'yellow_fever_cases': 'Yellow Fever Cases',
    'yellow_fever_test_indicator': 'Yellow Fever Test Indicator',
}
DIMENSIONS = {'StateName': 'State', 'MunicipalityName': 'Municipality', 'Sex': 'Sex'}
GRANULARITIES = {'week': 'Week', 'month': 'Month', 'quarter': 'Quarter'}

VIEW_TYPES = {
    'BAR': 'BAR_GRAPH',
    'BAR_STACKED': 'BAR_GRAPH',
    'HEATTILES': 'HEATTILES',
    'HIERARCHY': 'EXPANDOTREE',
    'LINE': 'TIME',
    'MAP': 'MAP',
    'NUMBER_TREND': 'NUMBER_TREND',
    'PIE': 'PIE',
    'TABLE': 'TABLE',
}

# (visualization type, title, fields, groups); a group is a dimension id or a
# granularity id.
MIXED = (
    ('BAR', 'Cases by state', ['yellow_fever_cases'], ['StateName']),
    (
        'LINE',
        'Cases by month and state',
        ['yellow_fever_cases'],
        ['month', 'StateName'],
    ),
    ('TABLE', 'Cases by state and sex', ['yellow_fever_cases'], ['StateName', 'Sex']),
    ('MAP', 'Cases by municipality', ['yellow_fever_cases'], ['MunicipalityName']),
    (
        'HIERARCHY',
        'Cases by state and municipality',
        ['yellow_fever_cases'],
        ['StateName', 'MunicipalityName'],
    ),
    ('PIE', 'Cases by sex', ['yellow_fever_cases'], ['Sex']),
)
WIDE = MIXED + (
    ('LINE', 'Cases by week', ['yellow_fever_cases'], ['week']),
    (
        'HEATTILES',
        'Cases by week and state',
        ['yellow_fever_cases'],
        ['week', 'StateName'],
    ),
    ('BAR_STACKED', 'Cases by month and sex', ['yellow_fever_cases'], ['month', 'Sex']),
    (
        'TABLE',
        'Cases by municipality and month',
        ['yellow_fever_cases', 'yellow_fever_test_indicator'],
        ['MunicipalityName', 'month'],
    ),
    ('NUMBER_TREND', 'Total cases', ['yellow_fever_cases'], []),
    (
        'LINE',
        'Cases by quarter and state',
        ['yellow_fever_cases'],
        ['quarter', 'StateName'],
    ),
)
# The largest responses: every municipality, or weekly series.
HEAVY = (
    (
        'TABLE',
        'Cases and tests by municipality and month',
        ['yellow_fever_cases', 'yellow_fever_test_indicator'],
        ['MunicipalityName', 'month'],
    ),
    (
        'HEATTILES',
        'Cases by week and state',
        ['yellow_fever_cases'],
        ['week', 'StateName'],
    ),
    (
        'LINE',
        'Cases by week and municipality',
        ['yellow_fever_cases'],
        ['week', 'MunicipalityName'],
    ),
    (
        'HIERARCHY',
        'Cases by state, municipality and sex',
        ['yellow_fever_cases'],
        ['StateName', 'MunicipalityName', 'Sex'],
    ),
)
DASHBOARDS = {
    'perf-mixed-6': ('Perf: six tiles, one per visualization family', MIXED),
    'perf-wide-12': ('Perf: twelve tiles', WIDE),
    'perf-heavy-4': ('Perf: four large tiles', HEAVY),
}

# Where the model's default disagrees with the frontend's: the model defaults a
# table to the Custom theme without a custom theme, which the frontend rejects
# (TableSettings/index.js); the frontend's own default is Default.
VIEW_SETTINGS = {'TABLE': {'activeTheme': 'Default'}}

TILE_COLUMNS = 50
TILE_ROWS = 40


def field(field_id):
    return {
        'id': field_id,
        'calculation': {
            'type': 'SUM',
            'filter': {'type': 'FIELD', 'fieldId': field_id},
        },
        'canonicalName': FIELDS[field_id],
        'shortName': FIELDS[field_id],
        'userDefinedLabel': '',
        'customizableFilterItems': [],
        'showNullAsZero': False,
    }


def group(group_id):
    if group_id in GRANULARITIES:
        return {
            'type': 'GROUPING_GRANULARITY',
            'item': {
                'granularity': group_id,
                'includeTotal': False,
                'name': GRANULARITIES[group_id],
            },
        }
    return {
        'type': 'GROUPING_DIMENSION',
        'item': {
            'dimension': group_id,
            'includeAll': False,
            'includeNull': False,
            'includeTotal': False,
            'name': DIMENSIONS[group_id],
        },
    }


# What the frontend derives from the query selections when a user builds a
# tile (QueryResultGrouping.fromGroupingItem, QueryResultSeries); with these
# empty, tiles throw while rendering.
def grouping(group_id):
    if group_id in GRANULARITIES:
        return {
            'id': 'timestamp',
            'type': 'DATE',
            'displayValueFormat': group_id,
            'label': GRANULARITIES[group_id],
        }
    return {
        'id': group_id,
        'type': 'STRING',
        'displayValueFormat': 'DEFAULT',
        'label': DIMENSIONS[group_id],
    }


SERIES_COLORS = ('#4E79A7', '#F28E2B')


def series_settings(field_ids):
    return {
        'seriesObjects': {
            # The model's default format is '0%'; the frontend's is 'none'
            # (QueryResultSeries.defaultValues).
            f: {
                'id': f,
                'color': SERIES_COLORS[i],
                'label': FIELDS[f],
                'dataLabelFormat': 'none',
            }
            for i, f in enumerate(field_ids)
        },
        'seriesOrder': list(field_ids),
    }


# View types whose settings name one field to show; the model defaults it to ''
# and the frontend then finds no series (ExpandoTree/index.jsx).
SELECTED_FIELD_VIEW_TYPES = {'EXPANDOTREE', 'HEATTILES', 'MAP', 'NUMBER_TREND'}


def view_settings(view_type, field_ids):
    settings = {'seriesSettings': series_settings(field_ids)}
    specific = dict(VIEW_SETTINGS.get(view_type, {}))
    if view_type in SELECTED_FIELD_VIEW_TYPES:
        specific['selectedField'] = field_ids[0]
    if specific:
        settings['viewSpecificSettings'] = specific
    return settings


def tile(index, visualization_type, title, field_ids, group_ids):
    view_type = VIEW_TYPES[visualization_type]
    return {
        'id': f'tile-{index}',
        # Two tiles per row on the 100-column grid.
        'position': {
            'x': (index % 2) * TILE_COLUMNS,
            'rowCount': TILE_ROWS,
            'columnCount': TILE_COLUMNS,
        },
        'item': {
            'type': 'QUERY_ITEM',
            'visualizationType': visualization_type,
            'querySelections': {
                'fields': [field(f) for f in field_ids],
                'filters': [],
                'groups': [group(g) for g in group_ids],
            },
            'queryResultSpec': {
                'groupBySettings': {
                    'groupings': {
                        g['id']: g
                        for g in (grouping(group_id) for group_id in group_ids)
                    }
                },
                'titleSettings': {'title': title},
                'viewTypes': [view_type],
                'visualizationSettings': {
                    view_type: view_settings(view_type, field_ids)
                },
            },
        },
    }


def specification(title, tiles):
    compact = {
        'version': LATEST_VERSION,
        'items': [tile(i, *t) for i, t in enumerate(tiles)],
        'options': {'title': title},
    }
    return related.to_dict(related.to_model(DashboardSpecification, compact))


def main():
    out = {
        slug: specification(title, tiles) for slug, (title, tiles) in DASHBOARDS.items()
    }
    json.dump(out, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
