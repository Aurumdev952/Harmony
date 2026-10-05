'''WP-0k: `POST /api2/user`, Potion's inherited create, refuses a username equal
ignoring case to another account's, through the real route.'''

import pytest


def _create(admin, username):
    return admin.request(
        'POST',
        '/api2/user',
        {
            'username': username,
            'firstName': 'New',
            'lastName': 'User',
            'phoneNumber': '',
        },
    )


@pytest.mark.parametrize('spelling', [str.upper, str.title])
def test_create_refuses_another_case_of_an_existing_username(make_user, spelling):
    admin = make_user(roles=['admin'])
    existing = make_user()

    response = _create(admin, spelling(existing.username))

    assert response.status_code == 400, response.get_data(as_text=True)[:300]
    users = admin.request('GET', '/api2/user').get_json()
    taken = [
        user['username']
        for user in users
        if user['username'].lower() == existing.username.lower()
    ]
    assert taken == [existing.username]


def test_create_accepts_a_new_username(make_user):
    admin = make_user(roles=['admin'])

    response = _create(admin, 'brand.new.account@escalation.test')

    assert response.status_code in (200, 201), response.get_data(as_text=True)[:300]
