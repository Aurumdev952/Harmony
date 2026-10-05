'''WP-0j (decision 0005): a non-superuser may change the username of, or reset
the password of, only a user whose grants are among its own. Otherwise renaming
the user to an address the caller reads, then resetting the password, hands
the caller the user's account (H5).
'''

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace

import pytest

from models.alchemy.permission import (
    Permission,
    Resource,
    ResourceRole,
    ResourceTypeEnum,
    Role,
)
from models.alchemy.security_group import Group
from models.alchemy.user import User, UserAcl

_USER_EDITOR = ['manager', 'user_admin']


@pytest.fixture(name='db')
def fixture_db(app):
    with app.app_context():
        yield app.extensions['sqlalchemy'].db


@pytest.fixture(name='mailer')
def fixture_mailer(app, monkeypatch):
    '''Stands in for the reset-password mail: the recipients of every message
    handed to the notification service.
    '''
    sent: list[str] = []
    monkeypatch.setattr(
        app,
        'email_renderer',
        SimpleNamespace(
            create_password_reset_message=lambda _by, user, _link: user.username
        ),
        raising=False,
    )
    monkeypatch.setattr(
        app,
        'notification_service',
        SimpleNamespace(send_email=sent.append),
        raising=False,
    )
    # The harness does not register the login pages the link points at.
    monkeypatch.setattr(
        'web.server.routes.views.admin.url_for',
        lambda *_args, **_kwargs: 'http://harmony.invalid/user/reset-password',
    )
    return sent


@pytest.fixture(name='refusals')
def fixture_refusals(caplog):
    '''The WARNING audit lines of refusals logged so far.'''
    # The app logger does not propagate to the root logger caplog listens on.
    app_logger = logging.getLogger('ZenysisLogger')
    app_logger.addHandler(caplog.handler)
    yield lambda: [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and 'Refused' in record.getMessage()
    ]
    app_logger.removeHandler(caplog.handler)


def _name(prefix: str) -> str:
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


def _attacker_address() -> str:
    return f'attacker-{uuid.uuid4().hex[:8]}@escalation.test'


def _make_group(db, roles=(), users=()) -> int:
    group = Group(
        name=_name('group'),
        roles=[db.session.query(Role).filter_by(name=r).one() for r in roles],
        users=db.session.query(User).filter(User.id.in_([u.id for u in users])).all(),
    )
    db.session.add(group)
    db.session.commit()
    return group.id


def _make_dashboard(db) -> int:
    resource = Resource(
        resource_type_id=ResourceTypeEnum.DASHBOARD.value,
        name=_name('dashboard'),
        label='Dashboard',
    )
    db.session.add(resource)
    db.session.commit()
    return resource.id


def _give_acl(db, user_id: int, resource_role_name: str, dashboard_id: int) -> None:
    resource_role = (
        db.session.query(ResourceRole).filter_by(name=resource_role_name).one()
    )
    db.session.add(
        UserAcl(
            user_id=user_id, resource_role_id=resource_role.id, resource_id=dashboard_id
        )
    )
    db.session.commit()


def _ensure_role(db, name: str, user_permissions=()) -> None:
    '''A role holding the given USER permissions, created once per session.'''
    if db.session.query(Role).filter_by(name=name).one_or_none():
        return
    permissions = [
        db.session.query(Permission)
        .filter_by(resource_type_id=ResourceTypeEnum.USER.value, permission=p)
        .one()
        for p in user_permissions
    ]
    db.session.add(Role(name=name, label=name, permissions=permissions))
    db.session.commit()


def _user(db, user_id: int) -> User:
    db.session.expire_all()
    return db.session.query(User).get(user_id)


def _resent_body(db, user_id: int, username: str) -> dict:
    '''A `PATCH /api2/user/<id>` body as the admin UI sends it: every role,
    group and ACL the user has, sent again, with a new username.
    '''
    user = _user(db, user_id)
    return {
        '$uri': f'/api2/user/{user_id}',
        'username': username,
        'firstName': user.first_name,
        'lastName': user.last_name,
        'phoneNumber': '',
        'status': 'active',
        'acls': [
            {
                '$uri': '',
                'resourceRole': {
                    '$uri': '',
                    'name': acl.resource_role.name,
                    'resourceType': 'DASHBOARD',
                },
                'resource': {
                    '$uri': '',
                    'label': acl.resource.label,
                    'name': acl.resource.name,
                    'resourceType': 'DASHBOARD',
                },
            }
            for acl in user.acls
        ],
        'apiTokens': [],
        'roles': [f'/api2/role/{role.id}' for role in user.roles],
        'groups': [f'/api2/group/{group.id}' for group in user.groups],
    }


def _rename(db, caller, user_id: int, username: str):
    return caller.request(
        'PATCH', f'/api2/user/{user_id}', _resent_body(db, user_id, username)
    )


def _reset(caller, user_id: int):
    return caller.request('POST', f'/api2/user/{user_id}/reset_password')


# Targets holding a grant the caller does not hold.


def _admin_through_group(db, make_user, _actor=None):
    target = make_user()
    _make_group(db, roles=['admin'], users=[target])
    return target


def _role_not_held(role_name):
    def target(_db, make_user, _actor):
        return make_user([role_name])

    target.__name__ = f'holds_{role_name}'
    return target


def _group_not_joined(db, make_user, _actor):
    # The group grants nothing the caller lacks; membership itself is the grant.
    target = make_user()
    _make_group(db, roles=['manager'], users=[target])
    return target


def _dashboard_acl(db, make_user, _actor):
    target = make_user()
    _give_acl(db, target.id, 'dashboard_admin', _make_dashboard(db))
    return target


def _dashboard_acl_the_caller_only_views(db, make_user, actor):
    # The caller's `view_resource` there covers one of the target's needs, not all.
    dashboard_id = _make_dashboard(db)
    _give_acl(db, actor.id, 'dashboard_viewer', dashboard_id)
    target = make_user()
    _give_acl(db, target.id, 'dashboard_admin', dashboard_id)
    return target


def _dashboard_acl_on_another_dashboard(db, make_user, actor):
    # The same resource role on a different dashboard covers nothing.
    _give_acl(db, actor.id, 'dashboard_admin', _make_dashboard(db))
    target = make_user()
    _give_acl(db, target.id, 'dashboard_admin', _make_dashboard(db))
    return target


_HIGHER_TARGETS = pytest.mark.parametrize(
    'make_target',
    [
        _admin_through_group,
        _role_not_held('all_sources_reader'),
        _role_not_held('exporter'),
        _role_not_held('group_admin'),
        _group_not_joined,
        _dashboard_acl,
        _dashboard_acl_the_caller_only_views,
        _dashboard_acl_on_another_dashboard,
    ],
    ids=lambda make_target: make_target.__name__.lstrip('_'),
)


def test_user_editor_cannot_take_over_an_admin_through_a_group(
    db, make_user, mailer, refusals
):
    '''H5 end to end: rename to the caller's address, then reset the password.'''
    actor = make_user(_USER_EDITOR)
    target = _admin_through_group(db, make_user)
    address = _attacker_address()

    renamed = _rename(db, actor, target.id, address)
    reset = _reset(actor, target.id)

    assert (renamed.status_code, reset.status_code) == (403, 403)
    assert _user(db, target.id).username == target.username
    assert not _user(db, target.id).reset_password_token
    assert mailer == []
    assert len(refusals()) == 2
    assert all(actor.username in line for line in refusals())


@_HIGHER_TARGETS
def test_user_editor_cannot_rename_a_user_holding_more(
    db, make_user, mailer, refusals, make_target
):
    actor = make_user(_USER_EDITOR)
    target = make_target(db, make_user, actor)
    groups = [group.id for group in _user(db, target.id).groups]

    response = _rename(db, actor, target.id, _attacker_address())

    assert response.status_code == 403
    assert _user(db, target.id).username == target.username
    assert [group.id for group in _user(db, target.id).groups] == groups
    assert mailer == []
    assert len(refusals()) == 1
    # The body names nothing the caller might not be able to list.
    body = response.get_data(as_text=True)
    assert 'admin' not in body and '/api2/' not in body


@pytest.mark.parametrize(
    'caller', [_USER_EDITOR, ['user_admin'], ['user_moderator']], ids=' + '.join
)
@_HIGHER_TARGETS
def test_a_reset_caller_cannot_reset_the_password_of_a_user_holding_more(
    db, make_user, mailer, refusals, make_target, caller
):
    _ensure_role(db, 'user_moderator', ['invite_user', 'reset_password'])
    actor = make_user(caller)
    target = make_target(db, make_user, actor)

    response = _reset(actor, target.id)

    assert response.status_code == 403
    assert not _user(db, target.id).reset_password_token
    assert mailer == []
    assert len(refusals()) == 1


# Unchanged: targets whose grants are among the caller's, superusers, and edits
# that keep the username.


def _no_grants(_db, make_user, _actor):
    return make_user()


def _same_roles(_db, make_user, _actor):
    return make_user(_USER_EDITOR)


def _fewer_roles_one_through_a_group(db, make_user, actor):
    # The caller holds `all_sources_reader` through a group it shares with the
    # target, and `manager` directly.
    target = make_user(['manager'])
    _make_group(db, roles=['all_sources_reader'], users=[actor, target])
    return target


def _acl_the_caller_holds_too(db, make_user, actor):
    target = make_user()
    dashboard_id = _make_dashboard(db)
    _give_acl(db, actor.id, 'dashboard_admin', dashboard_id)
    _give_acl(db, target.id, 'dashboard_admin', dashboard_id)
    return target


def _acl_covered_by_a_held_role(db, make_user, actor):
    # The `dashboard_admin` role allows the same on every dashboard.
    caller = db.session.query(User).get(actor.id)
    caller.roles.append(db.session.query(Role).filter_by(name='dashboard_admin').one())
    db.session.commit()
    target = make_user()
    _give_acl(db, target.id, 'dashboard_admin', _make_dashboard(db))
    return target


_LESSER_TARGETS = pytest.mark.parametrize(
    'make_target',
    [
        _no_grants,
        _same_roles,
        _fewer_roles_one_through_a_group,
        _acl_the_caller_holds_too,
        _acl_covered_by_a_held_role,
    ],
    ids=lambda make_target: make_target.__name__.lstrip('_'),
)


@_LESSER_TARGETS
def test_user_editor_renames_and_resets_a_user_holding_no_more(
    db, make_user, mailer, refusals, make_target
):
    actor = make_user(_USER_EDITOR)
    target = make_target(db, make_user, actor)
    address = _attacker_address()

    renamed = _rename(db, actor, target.id, address)
    reset = _reset(actor, target.id)

    assert (renamed.status_code, reset.status_code) == (200, 204)
    assert _user(db, target.id).username == address
    assert mailer == [address]
    assert refusals() == []


def test_user_editor_resets_its_own_password(make_user, mailer):
    actor = make_user(_USER_EDITOR)

    response = _reset(actor, actor.id)

    assert response.status_code == 204
    assert mailer == [actor.username]


def test_user_editor_still_edits_the_profile_of_a_user_holding_more(
    db, make_user, refusals
):
    actor = make_user(_USER_EDITOR)
    target = _admin_through_group(db, make_user)
    body = _resent_body(db, target.id, target.username)
    body['lastName'] = 'Renamed'

    response = actor.request('PATCH', f'/api2/user/{target.id}', body)

    assert response.status_code == 200
    edited = _user(db, target.id)
    assert (edited.username, edited.last_name) == (target.username, 'Renamed')
    assert edited.is_superuser()
    assert refusals() == []


def test_admin_renames_and_resets_an_admin_through_a_group(db, make_user, mailer):
    admin = make_user(['admin'])
    target = _admin_through_group(db, make_user)
    address = _attacker_address()

    renamed = _rename(db, admin, target.id, address)
    reset = _reset(admin, target.id)

    assert (renamed.status_code, reset.status_code) == (200, 204)
    assert mailer == [address]


def test_a_reset_without_reset_password_is_refused_before_the_target_is_judged(
    db, make_user, mailer, refusals
):
    actor = make_user(['manager'])
    target = _admin_through_group(db, make_user)

    response = _reset(actor, target.id)

    assert response.status_code == 401
    assert mailer == []
    assert refusals() == []


# "Superuser" is the identity: an admin account's token narrowed to the user
# permissions renames and resets like a non-superuser, and does not hold the
# admin role, even through a group it shares with the target.

_NARROWED_NEEDS = [
    ['view_resource', None, 'user'],
    ['edit_resource', None, 'user'],
    ['reset_password', None, 'user'],
    ['edit_user', None, 'site'],
]


def _token_caller(app, username: str, needs=None):
    # pylint: disable=import-outside-toplevel
    from flask_jwt_extended import create_access_token

    from web.server.util.authentication import create_user_access_token

    with app.test_request_context():
        token = (
            create_user_access_token(username)
            if needs is None
            else create_access_token(
                identity=username, user_claims={'needs': needs, 'query_needs': []}
            )
        )
    client = app.test_client()
    client.set_cookie('localhost', 'accessKey', token)
    return SimpleNamespace(
        request=lambda method, path, body=None: client.open(
            path, method=method, json=body
        )
    )


@pytest.mark.parametrize('narrowed', [False, True], ids=['full_session', 'narrowed'])
def test_a_narrowed_admin_token_cannot_take_over_an_admin_through_a_group(
    app, db, make_user, mailer, narrowed
):
    admin = make_user()
    target = make_user()
    _make_group(db, roles=['admin'], users=[admin, target])
    caller = _token_caller(app, admin.username, _NARROWED_NEEDS if narrowed else None)
    address = _attacker_address()

    renamed = _rename(db, caller, target.id, address)
    reset = _reset(caller, target.id)

    if narrowed:
        assert (renamed.status_code, reset.status_code) == (403, 403)
        assert _user(db, target.id).username == target.username
        assert mailer == []
    else:
        assert (renamed.status_code, reset.status_code) == (200, 204)
        assert mailer == [address]
