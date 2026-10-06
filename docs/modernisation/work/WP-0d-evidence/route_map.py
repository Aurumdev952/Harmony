"""Register the Flask blueprints on a bare app and print every URL rule."""

import os
from unittest import mock

os.environ.setdefault('ZEN_ENV', 'harmony_demo')

from web.server import app as app_module  # noqa: E402

app = app_module.create_app(skip_db_check=True)
for attr in (
    'template_renderer',
    'druid_context',
    'query_client',
    'cache',
    'notification_service',
):
    setattr(app, attr, mock.MagicMock())
with app.app_context():
    app_module._initialize_query_data(app)
    app_module._register_routes(app)
for rule in sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint)):
    methods = ','.join(sorted(m for m in rule.methods if m not in {'HEAD', 'OPTIONS'}))
    print(f'{rule.rule}\t{rule.endpoint}\t{methods}')
