from unittest import mock


def test_graphql_endpoint_is_not_registered(monkeypatch):
    # The endpoint served an empty graphene.Schema(); the frontend uses Hasura at /api/graphql.
    monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', 'postgresql://tests@db.invalid/tests')
    from web.server import app as app_module

    app = app_module.create_app(skip_db_check=True)
    for service in ('template_renderer', 'druid_context', 'cache'):
        setattr(app, service, mock.MagicMock())
    with app.app_context():
        app_module._initialize_query_data(app)
        app_module._register_routes(app)

    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert '/api/timeout' in rules
    assert '/graphql' not in rules
