from web.server.routes.api import ApiRouter


def test_broken_dimension_info_route_is_gone(bare_flask_app):
    # The handler called a method that never existed, so every request was a 500.
    # Repairing it would add a user-input path to an unfiltered Druid query (SEC-4).
    app = bare_flask_app()
    app.register_blueprint(ApiRouter(None, None).generate_blueprint())

    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    assert 'api.api_field_ids' in endpoints
    assert 'api.dimension_info' not in endpoints
