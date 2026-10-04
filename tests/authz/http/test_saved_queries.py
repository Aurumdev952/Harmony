'''Saved queries (`/api2/user_query_session`) carry no item permission: any
signed-in user reads any saved query and can attribute a new one to anyone.'''

from __future__ import annotations

import secrets

import pytest

from tests.authz.principals import SEED


@pytest.fixture(name='saved_query', scope='module')
def fixture_saved_query(stack) -> str:
    owner = stack.role_user('admin')
    owner_id = int(owner.user_uri.rsplit('/', 1)[1])
    response = stack.request(
        owner,
        'POST',
        '/api2/user_query_session/generate_link',
        {
            'queryUuid': None,
            'userId': owner_id,
            'queryBlob': {'authz': secrets.token_hex(8)},
        },
    )
    assert response.status_code == 200, response.text[:300]
    return response.json()


@pytest.mark.parametrize('role', list(SEED['roles']))
def test_any_signed_in_user_reads_any_saved_query(role, saved_query, stack):
    response = stack.request(
        stack.role_user(role), 'GET', f'/api2/user_query_session/{saved_query}'
    )
    assert response.status_code == 200
    assert response.json()['queryUuid'] == saved_query


def test_anonymous_cannot_read_a_saved_query(saved_query, stack):
    response = stack.request(
        stack.session_for('anonymous'), 'GET', f'/api2/user_query_session/{saved_query}'
    )
    assert response.status_code == 401


def test_a_saved_query_can_be_attributed_to_another_user(stack):
    actor = stack.role_user('query_runner')
    admin_id = int(stack.role_user('admin').user_uri.rsplit('/', 1)[1])
    response = stack.request(
        actor,
        'POST',
        '/api2/user_query_session/generate_link',
        {
            'queryUuid': None,
            'userId': admin_id,
            'queryBlob': {'authz': secrets.token_hex(8)},
        },
    )
    assert response.status_code == 200
    stored = stack.request(actor, 'GET', f'/api2/user_query_session/{response.json()}')
    assert stored.json()['userId'] == admin_id
