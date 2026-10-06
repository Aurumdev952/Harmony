'''The Flask GraphQL proxy talks to Hasura with the admin secret and a role
derived from the signed-in user, never one chosen by the client (SEC-2).'''

import os
from types import SimpleNamespace

import pytest
from flask import Flask
from flask_login import AnonymousUserMixin

os.environ.setdefault('ZEN_ENV', 'harmony_demo')
os.environ.setdefault('DEFAULT_SECRET_KEY', 'test-only-not-a-secret')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')

# pylint: disable=wrong-import-position
from web.server.routes import api
from web.server.routes.views import authentication

ADMIN_SECRET = 'test-admin-secret'
PUBLIC_QUERY = 'query patchDimensionServiceQuery { dimension_connection { edges { node { id } } } }'


class SignedInUser:
    is_authenticated = True
    from_jwt = False
    id = 42
    username = 'analyst@example.org'
    first_name = 'Ana'
    last_name = 'Lyst'


class ApiTokenUser(SignedInUser):
    from_jwt = True
    id = 7


@pytest.fixture(name='hasura_calls')
def fixture_hasura_calls(monkeypatch):
    calls = []

    def fake_post(url, json, headers=None, timeout=None):
        calls.append(
            SimpleNamespace(url=url, json=json, headers=headers or {}, timeout=timeout)
        )
        return SimpleNamespace(content=b'{"data": {}}', status_code=200)

    monkeypatch.setattr(api.requests, 'post', fake_post)
    return calls


def make_client(monkeypatch, user, admin_secret=ADMIN_SECRET, public_access=False):
    for module in (api, authentication):
        monkeypatch.setattr(module, 'current_user', user)
        monkeypatch.setattr(module, 'get_configuration', lambda key: public_access)

    here = os.path.dirname(os.path.abspath(__file__))
    app = Flask(__name__, root_path=here, instance_path=here)
    app.config['HASURA_HOST'] = 'http://hasura:8080'
    app.config['HASURA_ADMIN_SECRET'] = admin_secret
    # The proxy reads no router state, so skip __init__: it needs a full app
    # context on main and changes signature in WP-0c.
    router = api.ApiRouter.__new__(api.ApiRouter)
    app.add_url_rule(
        '/api/graphql', 'graphql', router.proxy_graphql_hasura, methods=['POST']
    )
    return app.test_client()


def test_signed_in_user_is_sent_as_user_role(monkeypatch, hasura_calls):
    client = make_client(monkeypatch, SignedInUser())

    response = client.post(
        '/api/graphql', json={'query': '{ field_connection { edges { node { id } } } }'}
    )

    assert response.status_code == 200
    assert hasura_calls[0].url == 'http://hasura:8080/v1beta1/relay'
    assert hasura_calls[0].headers == {
        'X-Hasura-Admin-Secret': ADMIN_SECRET,
        'X-Hasura-Role': 'user',
        'X-Hasura-User-Id': '42',
    }


def test_public_access_visitor_is_sent_as_anonymous_role(monkeypatch, hasura_calls):
    client = make_client(monkeypatch, AnonymousUserMixin(), public_access=True)

    response = client.post(
        '/api/graphql',
        json={'query': PUBLIC_QUERY},
        headers={'Referer': 'http://localhost/data-catalog'},
    )

    assert response.status_code == 200
    assert hasura_calls[0].headers == {
        'X-Hasura-Admin-Secret': ADMIN_SECRET,
        'X-Hasura-Role': 'anonymous',
    }


def test_client_cannot_choose_its_hasura_role(monkeypatch, hasura_calls):
    client = make_client(monkeypatch, SignedInUser())

    client.post(
        '/api/graphql',
        json={'query': '{ field_connection { edges { node { id } } } }'},
        headers={'X-Hasura-Role': 'admin', 'X-Hasura-Admin-Secret': 'guess'},
    )

    assert hasura_calls[0].headers['X-Hasura-Role'] == 'user'
    assert hasura_calls[0].headers['X-Hasura-Admin-Secret'] == ADMIN_SECRET


def test_full_access_api_token_is_sent_as_user_role(monkeypatch, hasura_calls):
    monkeypatch.setattr(api, 'get_jwt_claims', lambda: {'needs': {'*': True}})
    client = make_client(monkeypatch, ApiTokenUser())

    response = client.post(
        '/api/graphql', json={'query': '{ field_connection { edges { node { id } } } }'}
    )

    assert response.status_code == 200
    assert hasura_calls[0].headers == {
        'X-Hasura-Admin-Secret': ADMIN_SECRET,
        'X-Hasura-Role': 'user',
        'X-Hasura-User-Id': '7',
    }


def test_scoped_api_token_never_reaches_hasura(monkeypatch, hasura_calls):
    monkeypatch.setattr(api, 'get_jwt_claims', lambda: {'needs': {'view_query': True}})
    client = make_client(monkeypatch, ApiTokenUser())

    response = client.post('/api/graphql', json={'query': '{ __typename }'})

    assert response.status_code == 401
    assert not hasura_calls


def test_proxy_refuses_when_no_admin_secret_is_configured(monkeypatch, hasura_calls):
    client = make_client(monkeypatch, SignedInUser(), admin_secret='')

    response = client.post('/api/graphql', json={'query': '{ __typename }'})

    assert response.status_code == 503
    assert not hasura_calls


def test_signed_out_request_without_public_access_is_refused(monkeypatch, hasura_calls):
    client = make_client(monkeypatch, AnonymousUserMixin(), public_access=False)

    response = client.post('/api/graphql', json={'query': PUBLIC_QUERY})

    assert response.status_code == 401
    assert not hasura_calls
