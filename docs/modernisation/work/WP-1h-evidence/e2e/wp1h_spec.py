"""Print a complete latest-version dashboard spec with one text tile, with every
default filled in by the backend model."""

import json

import related

from models.python.dashboard.latest.model import (
    DashboardItemHolder,
    DashboardOptions,
    DashboardSpecification,
    Position,
    TextItemDefinition,
)
from models.python.dashboard.version import LATEST_VERSION

spec = DashboardSpecification(
    version=LATEST_VERSION,
    items=[
        DashboardItemHolder(
            id='wp1h-text',
            position=Position(x=0, row_count=8, column_count=60),
            item=TextItemDefinition(
                text='<h1>WP-1h render check</h1><p>Rendered by the self-hosted renderer.</p>',
            ),
        )
    ],
    options=DashboardOptions(title='WP-1h render check'),
)
print(json.dumps(related.to_dict(spec)))
