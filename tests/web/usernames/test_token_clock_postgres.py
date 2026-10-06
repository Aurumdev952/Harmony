"""WP-0k: the issued-before-account decision does not depend on the database's
time zone.

`user.created` is a naive timestamp the database writes with
`current_timestamp()`, so Postgres stores it in the session time zone, while a
token's `iat` is UTC seconds. Comparing the two in Python accepts a stale token
for the zone's offset behind UTC and refuses a valid one for the offset ahead
of it. These tests run a throwaway Postgres, the image `docker-compose.db.yaml`
pins, with the database's time zone set to UTC, +02:00 and -05:00.

Marked `stack` because they need docker; CI's unit job deselects them.
"""

import secrets
import shutil
import subprocess
import time
from datetime import datetime, timezone

import pytest
import sqlalchemy
from flask_jwt_extended import decode_token

from models.alchemy.user import User
from tests.web.usernames.conftest import build_app
from tests.web.usernames.tokens import session_token_without_account_id, signed_in_id

pytestmark = pytest.mark.stack

POSTGRES_IMAGE = (
    'postgres@sha256:f7d23353e1b15400d22ebe31189f4d314b87a4c129cc400c8c2d8d4ca127bf81'
)
USERNAME = 'clock.check@moh.gov.rw'
# Database name, Postgres time zone, its offset from UTC in hours. POSIX zone
# names invert the sign: Etc/GMT-2 is two hours ahead of UTC.
ZONES = [
    ('zone_utc', 'UTC', 0),
    ('zone_plus_two', 'Etc/GMT-2', 2),
    ('zone_minus_five', 'Etc/GMT+5', -5),
]


def _docker(*args):
    return subprocess.run(
        ['docker', *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture(name='server_url', scope='module')
def fixture_server_url():
    if shutil.which('docker') is None:
        pytest.skip('needs docker')
    password = secrets.token_hex(16)
    container = _docker(
        'run', '-d', '--rm', '-e', f'POSTGRES_PASSWORD={password}',
        '-p', '127.0.0.1::5432', POSTGRES_IMAGE,
    )  # fmt: skip
    try:
        port = _docker('port', container, '5432/tcp').rsplit(':', 1)[1]
        url = f'postgresql://postgres:{password}@127.0.0.1:{port}'
        engine = sqlalchemy.create_engine(
            f'{url}/postgres', isolation_level='AUTOCOMMIT'
        )
        _wait_for(engine)
        with engine.connect() as connection:
            for database, zone, _ in ZONES:
                connection.execute(f'CREATE DATABASE {database}')
                connection.execute(f"ALTER DATABASE {database} SET timezone = '{zone}'")
        engine.dispose()
        yield url
    finally:
        subprocess.run(['docker', 'rm', '-f', container], capture_output=True)


def _wait_for(engine):
    # The image's init server listens on the socket only, so a TCP connection
    # means the final server is up.
    deadline = time.monotonic() + 60
    while True:
        try:
            with engine.connect() as connection:
                connection.execute('SELECT 1')
            return
        except sqlalchemy.exc.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


@pytest.fixture(name='zoned_app', params=ZONES, ids=[zone[1] for zone in ZONES])
def fixture_zoned_app(request, server_url):
    database, _, offset_hours = request.param
    app, db = build_app(f'{server_url}/{database}')
    with app.app_context():
        columns = ', '.join(
            f'"{column.name}" SERIAL PRIMARY KEY'
            if column.name == 'id'
            else f'"{column.name}" {column.type.compile(dialect=db.engine.dialect)}'
            for column in User.__table__.columns
        )
        with db.engine.begin() as connection:
            connection.execute('DROP TABLE IF EXISTS "user"')
            connection.execute(f'CREATE TABLE "user" ({columns})')
        # Through the model, so `created` gets the column default, as for every
        # account the app creates.
        db.session.add(
            User(
                username=USERNAME,
                password='',
                reset_password_token='',
                first_name='Clock',
                last_name='Check',
                phone_number='',
                status_id=1,
            )
        )
        db.session.commit()
        created = db.session.query(User.created).scalar()
        db.session.remove()
    yield app, db, created, offset_hours
    with app.app_context():
        db.engine.dispose()


def _move_created(app, db, seconds):
    with app.app_context():
        with db.engine.begin() as connection:
            connection.execute(
                sqlalchemy.text(
                    'UPDATE "user" SET created = created + '
                    "make_interval(secs => :seconds)"
                ),
                {'seconds': seconds},
            )


def test_created_is_written_in_the_database_time_zone(zoned_app):
    """The premise: the stored value moves with the zone."""
    _, _, created, offset_hours = zoned_app
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)

    assert abs((created - utc_now).total_seconds() - offset_hours * 3600) < 60


def test_session_issued_after_the_account_signs_in(zoned_app):
    app, db, _, _ = zoned_app
    _move_created(app, db, -2)
    token = session_token_without_account_id(app, USERNAME)

    assert signed_in_id(app, token) == 1


def test_session_issued_in_the_second_the_account_was_created_signs_in(zoned_app):
    app, db, _, _ = zoned_app
    token = session_token_without_account_id(app, USERNAME)
    with app.app_context():
        with db.engine.begin() as connection:
            # The last microsecond of the token's `iat` second, in the
            # database's own zone.
            connection.execute(
                sqlalchemy.text(
                    'UPDATE "user" SET created = CAST(to_timestamp(:iat) AS '
                    "TIMESTAMP) + interval '0.999999 seconds'"
                ),
                {'iat': _issued_at(app, token)},
            )

    assert signed_in_id(app, token) == 1


def test_session_issued_before_the_account_is_refused(zoned_app):
    app, db, _, _ = zoned_app
    token = session_token_without_account_id(app, USERNAME)
    _move_created(app, db, 2)

    assert signed_in_id(app, token) is None


def _issued_at(app, token):
    with app.app_context():
        return decode_token(token)['iat']
