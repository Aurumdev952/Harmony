"""WP-1h: the render token (SEC-7).

A render token signs the renderer's browser in as the requesting user, for one
dashboard and one render: it is refused once the render that minted it returns.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import pytest
from flask import Flask, g, jsonify
from flask_jwt_extended import JWTManager, create_access_token, decode_token
from flask_login import LoginManager, UserMixin, current_user
from flask_principal import Identity, ItemNeed
from freezegun import freeze_time

from config.loader import import_configuration_module
from models.python.permissions import DimensionFilter, QueryNeed
from tests.web.render.fakes import DictCache
from web.server.security.render_tokens import (
    RENDER_CLAIM,
    RENDER_POLICY_CLAIM,
    is_render_request,
    render_token,
)
from web.server.security.signal_handlers import (
    _install_token_needs,
    install_login_manager_signal_handlers,
    query_policy_fingerprint,
)

USERNAME = 'north@tests.invalid'
RESOURCE_ID = 7
STATE = 'StateName'  # an AUTHORIZABLE_DIMENSIONS entry in harmony_demo
NOT_SUPERUSER = SimpleNamespace(can=lambda: False)


class _User(UserMixin):
    id = USERNAME
    username = USERNAME


@contextmanager
def _users_table():
    def find_one_by_fields(_model, _case_sensitive, fields):
        return _User() if fields == {'username': USERNAME} else None

    yield SimpleNamespace(find_one_by_fields=find_one_by_fields)


@pytest.fixture(name='app')
def fixture_app(bare_flask_app) -> Flask:
    app = bare_flask_app()
    app.config.update(
        SECRET_KEY='tests-web-placeholder-session-key',
        JWT_SECRET_KEY='tests-web-placeholder-jwt-key',
        JWT_TOKEN_LOCATION=['headers', 'cookies'],
        JWT_ACCESS_COOKIE_NAME='accessKey',
        JWT_CSRF_METHODS=[],
    )
    JWTManager(app)
    app.zen_config = import_configuration_module('harmony_demo')
    cache = DictCache()
    cache.memoize = lambda: lambda function: function
    app.cache = cache
    install_login_manager_signal_handlers(app, LoginManager(app))
    app.add_url_rule(
        '/whoami',
        'whoami',
        lambda: jsonify(
            user=current_user.is_authenticated and current_user.username,
            render=is_render_request(),
        ),
    )
    return app


@pytest.fixture(autouse=True)
def fixture_users_table():
    with mock.patch('web.server.security.signal_handlers.Transaction', _users_table):
        yield


def _whoami(app: Flask, token: str) -> dict:
    client = app.test_client()
    client.set_cookie('localhost', 'accessKey', token)
    return client.get('/whoami').get_json()


@contextmanager
def _minted(app: Flask, ttl_seconds: int = 60, policy=None):
    with app.test_request_context('/'):
        with render_token(
            USERNAME, RESOURCE_ID, policy=policy, ttl_seconds=ttl_seconds
        ) as token:
            yield token


def _claims(app: Flask, token: str) -> dict:
    with app.app_context():
        return decode_token(token)


def test_token_signs_in_as_the_requesting_user_for_one_dashboard(app):
    with _minted(app) as token:
        claims = _claims(app, token)

    assert claims['identity'] == USERNAME
    assert claims['user_claims']['needs'] == [
        ['view_resource', RESOURCE_ID, 'dashboard']
    ]
    assert claims['user_claims']['query_needs'] == ['*']
    assert claims['user_claims'][RENDER_CLAIM]
    assert RENDER_POLICY_CLAIM not in claims['user_claims']


def test_token_is_short_lived(app):
    with _minted(app, ttl_seconds=60) as token:
        claims = _claims(app, token)

    assert claims['exp'] - claims['iat'] == 60


def test_each_render_gets_its_own_token(app):
    with _minted(app) as first, _minted(app) as second:
        assert first != second
        assert (
            _claims(app, first)['user_claims'][RENDER_CLAIM]
            != _claims(app, second)['user_claims'][RENDER_CLAIM]
        )


def test_token_signs_the_browser_in_while_its_render_runs(app):
    with _minted(app) as token:
        # Every request the dashboard page makes during the render carries it.
        assert _whoami(app, token) == {'user': USERNAME, 'render': True}
        assert _whoami(app, token) == {'user': USERNAME, 'render': True}


def test_token_is_refused_once_its_render_returns(app):
    with _minted(app) as token:
        pass

    assert _whoami(app, token) == {'user': False, 'render': False}


def test_token_is_refused_when_the_render_fails(app):
    with pytest.raises(RuntimeError):
        with _minted(app) as token:
            raise RuntimeError('renderer unreachable')

    assert _whoami(app, token) == {'user': False, 'render': False}


def test_token_is_refused_after_it_expires_while_still_registered(app):
    with freeze_time(datetime.utcnow()) as clock:
        with _minted(app, ttl_seconds=60) as token:
            clock.tick(timedelta(seconds=61))

            assert _whoami(app, token)['user'] is False


def test_a_render_id_that_is_not_registered_is_refused(app):
    with _minted(app) as token:
        render_id = _claims(app, token)['user_claims'][RENDER_CLAIM]
        app.cache.values.clear()

        assert _whoami(app, token)['user'] is False
        assert render_id


def test_an_ordinary_session_token_is_not_a_render_request(app):
    with app.test_request_context('/'):
        token = create_access_token(identity=USERNAME, expires_delta=timedelta(60))

    assert _whoami(app, token) == {'user': USERNAME, 'render': False}


# The query policy a render runs under.


def _policy(*include_values: str) -> QueryNeed:
    if include_values:
        return QueryNeed([DimensionFilter(STATE, include_values=include_values)])
    return QueryNeed([DimensionFilter(STATE, all_values=True)])


VIEW_DASHBOARD = ItemNeed('view_resource', RESOURCE_ID, 'dashboard')
EDIT_DASHBOARD = ItemNeed('edit_resource', RESOURCE_ID, 'dashboard')


@contextmanager
def _signed_in(app: Flask, provides):
    with app.test_request_context('/'), mock.patch(
        'web.server.security.signal_handlers.SuperUserPermission',
        lambda: NOT_SUPERUSER,
    ):
        g.identity = Identity(USERNAME)
        g.identity.provides = set(provides)
        yield g.identity


def _policy_digest(app: Flask, provides) -> str:
    with _signed_in(app, provides):
        return query_policy_fingerprint()


def _page_load(app: Flask, provides, policy) -> set:
    """What a request signed in with a render token may do, given the account's
    permissions at the time the page loads.
    """
    with _minted(app, policy=policy) as token:
        claims = _claims(app, token)['user_claims']
    with _signed_in(app, provides) as identity, mock.patch(
        'web.server.security.signal_handlers.get_jwt_claims', lambda: claims
    ):
        _install_token_needs(identity)
        return identity.provides


NORTH_ACCOUNT = {VIEW_DASHBOARD, EDIT_DASHBOARD, _policy('North')}


def test_token_carries_the_policy_digest_it_was_requested_under(app):
    digest = _policy_digest(app, NORTH_ACCOUNT)

    with _minted(app, policy=digest) as token:
        claims = _claims(app, token)['user_claims']

    assert claims[RENDER_POLICY_CLAIM] == digest
    assert claims['query_needs'] == ['*']


def test_unchanged_policy_grants_view_and_the_accounts_own_policy(app):
    provides = _page_load(app, NORTH_ACCOUNT, _policy_digest(app, NORTH_ACCOUNT))

    assert provides == {VIEW_DASHBOARD, _policy('North')}


def test_a_token_without_a_digest_resolves_the_accounts_policy(app):
    provides = _page_load(app, NORTH_ACCOUNT, None)

    assert provides == {VIEW_DASHBOARD, _policy('North')}


@pytest.mark.parametrize(
    'changed',
    [
        {VIEW_DASHBOARD, _policy()},
        {VIEW_DASHBOARD, _policy('North', 'South')},
        {VIEW_DASHBOARD, _policy('South')},
        {VIEW_DASHBOARD},
    ],
    ids=['widened-to-all', 'widened', 'moved', 'removed'],
)
def test_a_policy_change_after_the_request_leaves_the_render_with_nothing(app, changed):
    provides = _page_load(app, changed, _policy_digest(app, NORTH_ACCOUNT))

    assert provides == set()


def test_viewers_with_the_same_policy_have_the_same_digest(app):
    assert _policy_digest(app, NORTH_ACCOUNT) == _policy_digest(
        app, {VIEW_DASHBOARD, _policy('North')}
    )
    assert _policy_digest(app, NORTH_ACCOUNT) != _policy_digest(
        app, {VIEW_DASHBOARD, _policy('South')}
    )
