"""WP-0l (decision 0012): the data-access name lookups on a real Postgres.

`find_one_by_fields(..., case_sensitive=False)` filtered with `ILIKE <value>`
and returned `.first()` with no ordering, so `_` and `%` in a name matched
other rows, and the row stored first won. After WP-0l the comparison is
`lower(field) == lower(value)`: still case-insensitive, never a pattern.

Each look-alike is stored before the named row, the order in which the
pattern lookup returned the look-alike.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator

import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

import models.alchemy
from models.alchemy.base import Base
from models.alchemy.permission import (
    Resource,
    ResourceRole,
    ResourceType,
    ResourceTypeEnum,
)
from models.alchemy.security_group import Group
from models.alchemy.user import User, UserStatus, UserStatusEnum
from web.server.data.data_access import find_one_by_fields
from web.server.routes.views.core import try_get_role_and_resource
from web.server.routes.views.resource import get_resource_by_type_and_name

# Relationships resolve only once every model is mapped, as in app_base.py.
for _module in pkgutil.iter_modules(models.alchemy.__path__):
    importlib.import_module(f"models.alchemy.{_module.name}")

DASHBOARD = ResourceTypeEnum.DASHBOARD.value
ALERT = ResourceTypeEnum.ALERT.value


@pytest.fixture(name="session")
def fixture_session(bare_flask_app, postgres_database: str) -> Iterator:
    app: Flask = bare_flask_app()
    app.config.update(
        SQLALCHEMY_DATABASE_URI=postgres_database,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db = SQLAlchemy(app, model_class=Base)
    with app.app_context():
        Base.metadata.create_all(
            db.engine,
            tables=[
                ResourceType.__table__,
                Resource.__table__,
                ResourceRole.__table__,
                UserStatus.__table__,
                User.__table__,
                Group.__table__,
            ],
        )
        db.session.add_all(ResourceType(id=e.value, name=e) for e in ResourceTypeEnum)
        db.session.add(UserStatus(id=1, status=UserStatusEnum.ACTIVE))
        db.session.commit()
        db.session.add(
            ResourceRole(name="dashboard_viewer", resource_type_id=DASHBOARD)
        )
        db.session.commit()
        yield db.session
        db.session.remove()
        db.engine.dispose()


def _store(session, *rows) -> list[int]:
    """Commits each row on its own, in order, so the first is stored first."""
    ids = []
    for row in rows:
        session.add(row)
        session.commit()
        ids.append(row.id)
    return ids


def _dashboard(name: str, type_id: int = DASHBOARD) -> Resource:
    return Resource(resource_type_id=type_id, name=name, label=name)


def _user(username: str) -> User:
    return User(username=username, status_id=1)


def test_an_underscore_in_a_resource_name_matches_only_itself(session):
    _, named_id = _store(session, _dashboard("axb"), _dashboard("a_b"))

    found = find_one_by_fields(Resource, False, {"name": "a_b"}, session)

    assert (found.id, found.name) == (named_id, "a_b")


def test_a_resource_name_only_a_look_alike_matches_finds_nothing(session):
    _store(session, _dashboard("axb"))

    assert find_one_by_fields(Resource, False, {"name": "a_b"}, session) is None


def test_a_percent_in_a_group_name_matches_only_itself(session):
    _store(session, Group(name="team-q-a"))

    assert find_one_by_fields(Group, False, {"name": "team%a"}, session) is None


def test_an_underscore_in_a_username_matches_only_itself(session):
    _, named_id = _store(
        session, _user("john.doe@name.invalid"), _user("john_doe@name.invalid")
    )

    found = find_one_by_fields(
        User, False, {"username": "john_doe@name.invalid"}, session
    )

    assert found.id == named_id


def test_a_case_insensitive_lookup_still_ignores_case(session):
    """Unchanged by WP-0l."""
    (named_id,) = _store(session, _dashboard("plain"))

    found = find_one_by_fields(Resource, False, {"name": "PLAIN"}, session)

    assert found.id == named_id


def test_a_case_sensitive_lookup_still_respects_case(session):
    """Unchanged by WP-0l."""
    _store(session, _dashboard("plain"))

    assert find_one_by_fields(Resource, True, {"name": "PLAIN"}, session) is None


def test_role_and_resource_lookup_resolves_the_named_dashboard(session):
    """Path A, before WP-0l: `add_user_acl` and `add_group_acl` resolved the
    dashboard they stored the ACL on through this lookup; they now take the
    resource itself. User and group ACLs sent with an empty `$uri`
    (`verify_acl_grants`) and the legacy `DELETE .../roles` routes
    (`delete_user_role`, `delete_group_role`) still resolve by name here."""
    _, named_id = _store(session, _dashboard("axb"), _dashboard("a_b"))

    _, _, resource = try_get_role_and_resource(
        "dashboard_viewer", ResourceTypeEnum.DASHBOARD, "a_b", session
    )

    assert resource.id == named_id


def test_resource_by_type_and_name_keeps_the_type(session):
    """Decision 0012 tracing note: the lookup behind `/api/authorization`
    joined its two conditions with Python `and`, which drops the type
    condition, so an alert stored first with the same name was returned."""
    _, dashboard_id = _store(
        session, _dashboard("same", type_id=ALERT), _dashboard("same")
    )

    found = get_resource_by_type_and_name("dashboard", "same")

    assert (found.id, found.resource_type_id) == (dashboard_id, DASHBOARD)
