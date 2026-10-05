'''Every principal against every check in decisions.yaml, through `is_authorized`.'''

from __future__ import annotations

import pytest
from flask import g

from tests.authz.principals import load_identity, principal_specs
from tests.authz.table import Row, rows
from web.server.routes.views.authorization import is_authorized

ROWS = rows()


@pytest.mark.parametrize('row', ROWS, ids=[r.id for r in ROWS])
def test_is_authorized(row: Row, request_ctx: None) -> None:
    load_identity(principal_specs()[row.principal])

    decision = is_authorized(
        row.permission, row.resource_type, row.resource_id, log_request=False
    )

    assert decision is row.allowed, sorted(map(repr, g.identity.provides))


def test_every_seeded_role_has_an_allow_and_a_deny() -> None:
    # RoleNeed('admin') satisfies every whitelisted check, so admin has no deny
    # here; its denials are the self-delete guard in tests/authz/http and the
    # loss of admin under an explicit-needs token (render_token:admin).
    outcomes: dict = {}
    for row in ROWS:
        outcomes.setdefault(row.principal, set()).add(row.allowed)
    lopsided = [
        principal
        for principal, seen in outcomes.items()
        if principal.startswith('role:') and seen != {True, False}
    ]
    assert lopsided == ['role:admin']
