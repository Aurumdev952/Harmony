'''tests/flask_isolation.py lets a later test register a resource with a new Api.

Joining an Api binds a Potion resource class to it and copies its relations'
routes into the class's own `routes`, so a second Api would register those routes
twice and Flask would refuse the duplicate endpoint.
'''

from flask_potion import Api, Resource
from flask_potion.routes import Relation

from tests.flask_isolation import restored_flask_globals


class _Owner(Resource):
    class Meta:
        name = 'isolation_owner'
        id_converter = 'int'


class _Owned(Resource):
    owner = Relation('isolation_owner', io='r')

    class Meta:
        name = 'isolation_owned'
        id_converter = 'int'


def _register(app):
    api = Api(app)
    api.add_resource(_Owner)
    api.add_resource(_Owned)
    return {rule.endpoint for rule in app.url_map.iter_rules()}


def test_a_resource_with_a_relation_joins_a_second_api_after_the_block(bare_flask_app):
    with restored_flask_globals():
        first = _register(bare_flask_app())

    assert _register(bare_flask_app()) == first
    assert 'isolation_owned_owner' in first


def _late_resource():
    # Like a module the full app imports while a test builds it.
    class _Late(Resource):
        owner = Relation('isolation_owner', io='r')

        class Meta:
            name = 'isolation_late'
            id_converter = 'int'

    return _Late


def test_a_resource_first_defined_inside_the_block_joins_a_second_api_after_it(
    bare_flask_app,
):
    with restored_flask_globals():
        late = _late_resource()
        api = Api(bare_flask_app())
        api.add_resource(_Owner)
        api.add_resource(late)

    second = Api(bare_flask_app())
    second.add_resource(_Owner)
    second.add_resource(late)

    assert 'isolation_late_owner' in {
        rule.endpoint for rule in second.app.url_map.iter_rules()
    }
