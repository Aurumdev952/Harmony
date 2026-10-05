"""WP-0i: the dashboard slug lookup ignores case and has no wildcards.

Every render route and `/api2/storage/retrieve` answer 404 for an unknown slug
and 403 for a dashboard the caller cannot view, so a wildcard lookup would let a
caller probe which slugs exist. The real `get_dashboard` runs here on SQLite.
"""

import pytest
import sqlalchemy
from sqlalchemy.orm import sessionmaker

from models.alchemy.dashboard import Dashboard
from web.server.routes.views.dashboard import get_dashboard


@pytest.fixture(name='session')
def fixture_session():
    engine = sqlalchemy.create_engine('sqlite://')
    columns = ', '.join(column.name for column in Dashboard.__table__.columns)
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text(f'CREATE TABLE dashboard ({columns})'))
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO dashboard (id, slug, resource_id, specification) "
                "VALUES (1, 'malaria-overview', 7, '{}')"
            )
        )
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.mark.parametrize(
    'slug', ['malaria-overview', 'Malaria-Overview', 'MALARIA-OVERVIEW']
)
def test_slug_matches_in_any_case(session, slug):
    assert get_dashboard(slug, session=session).resource_id == 7


@pytest.mark.parametrize(
    'slug', ['malaria%', '%', 'malaria_overview', '________________']
)
def test_like_metacharacters_match_nothing(session, slug):
    assert get_dashboard(slug, session=session) is None
