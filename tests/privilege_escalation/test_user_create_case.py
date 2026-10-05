'''WP-0k: `POST /api2/user`, Potion's inherited create, refuses a username equal
ignoring case to another account's, through the real route.'''

import pytest
from sqlalchemy import func


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


def _usernames_equal_ignoring_case(app, username):
    # pylint: disable=import-outside-toplevel
    from models.alchemy.user import User

    with app.app_context():
        return [
            user.username
            for user in User.query.filter(func.lower(User.username) == username.lower())
        ]


@pytest.mark.parametrize('spelling', [str.upper, str.title])
def test_create_refuses_another_case_of_an_existing_username(app, make_user, spelling):
    admin = make_user(roles=['admin'])
    existing = make_user()

    response = _create(admin, spelling(existing.username))

    assert response.status_code == 400, response.get_data(as_text=True)[:300]
    assert _usernames_equal_ignoring_case(app, existing.username) == [existing.username]


def test_create_accepts_a_new_username(app, make_user):
    admin = make_user(roles=['admin'])

    response = _create(admin, 'brand.new.account@escalation.test')

    assert response.status_code in (200, 201), response.get_data(as_text=True)[:300]
    assert _usernames_equal_ignoring_case(app, 'brand.new.account@escalation.test')
