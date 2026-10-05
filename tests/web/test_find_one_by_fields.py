"""`find_one_by_fields(..., case_sensitive=False)` matches a name exactly, ignoring case.

It used `ILIKE value`, so `_` and `%` in a name acted as wildcards and `.first()` returned
an arbitrary row among the matches: sharing dashboard `a_b` could store the ACL on `axb`
(decision 0012, WP-0l).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

from web.server.data.data_access import find_one_by_fields

_Base = declarative_base()


class _Named(_Base):
    __tablename__ = 'named'
    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False)
    kind = Column(Integer, nullable=False)


@pytest.fixture(name='session', params=['sqlite', 'postgres'])
def fixture_session(request: pytest.FixtureRequest) -> Iterator[Session]:
    url = (
        'sqlite://'
        if request.param == 'sqlite'
        else request.getfixturevalue('postgres_database')
    )
    engine = create_engine(url)
    _Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    # `axb` first, so a wildcard match on `a_b` would return it.
    session.add_all(
        [_Named(id=1, name='axb', kind=1), _Named(id=2, name='a_b', kind=1)]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _find(session: Session, fields: dict) -> _Named | None:
    return find_one_by_fields(_Named, False, fields, session)


@pytest.mark.parametrize('name', ['a_b', 'A_B'])
def test_underscore_matches_only_the_exact_name(session: Session, name: str) -> None:
    found = _find(session, {'name': name})
    assert found is not None and found.id == 2


@pytest.mark.parametrize('name', ['a%', '%', 'a_', '_xb', 'A_b%'])
def test_pattern_with_no_exact_match_finds_nothing(session: Session, name: str) -> None:
    assert _find(session, {'name': name}) is None


def test_underscore_does_not_match_another_row(session: Session) -> None:
    session.query(_Named).filter_by(id=2).delete()
    session.commit()
    assert _find(session, {'name': 'a_b'}) is None


def test_non_string_fields_still_compare_by_equality(session: Session) -> None:
    found = _find(session, {'name': 'AXB', 'kind': 1})
    assert found is not None and found.id == 1
    assert _find(session, {'name': 'axb', 'kind': 2}) is None
