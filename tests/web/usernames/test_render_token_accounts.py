'''WP-0k with WP-1h: a render token signs in through `account_for_token` like
every other token (bound by `user_id`, exact username, active, `iat`), and only
while its render is live (single use, SEC-7).'''

import pytest
import sqlalchemy

from tests.web.usernames.tokens import signed_in_id
from web.server.security.render_tokens import render_token

JANE = 8  # jane.doe@moh.gov.rw


class _Cache:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, timeout=None):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture(name='mint')
def fixture_mint(app, monkeypatch):
    '''Opens a render for account `user_id` and returns its token; the render
    stays live until the test ends or `close` is called.'''
    monkeypatch.setattr(app, 'cache', _Cache(), raising=False)
    renders = []

    def mint(user_id):
        with app.app_context():
            account = app.user_manager.get_user_by_id(user_id)
        with app.test_request_context('/'):
            render = render_token(account, 7, policy=None, ttl_seconds=120)
            token = render.__enter__()
        renders.append(render)
        return token

    def close():
        with app.test_request_context('/'):
            for render in renders:
                render.__exit__(None, None, None)

    mint.close = close
    yield mint
    close()


def _run(app, sql):
    with app.app_context():
        engine = app.extensions['sqlalchemy'].db.engine
        with engine.begin() as connection:
            connection.execute(sqlalchemy.text(sql))


def test_a_live_render_token_signs_in_its_account_and_a_spent_one_nobody(app, mint):
    token = mint(JANE)
    assert signed_in_id(app, token) == JANE

    mint.close()

    assert signed_in_id(app, token) is None


@pytest.mark.parametrize(
    'change',
    [
        'UPDATE "user" SET status_id = 2 WHERE id = 8',
        'UPDATE "user" SET username = \'jane.renamed@moh.gov.rw\' WHERE id = 8',
    ],
    ids=['deactivated', 'renamed'],
)
def test_a_live_render_token_signs_in_nobody_once_its_account_changes(
    app, mint, change
):
    token = mint(JANE)
    assert signed_in_id(app, token) == JANE

    _run(app, change)

    assert signed_in_id(app, token) is None
