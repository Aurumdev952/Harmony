"""A throwaway Postgres for tests that need real foreign keys, COPY and ON CONFLICT.

Import `postgres_database` into a conftest to use it. Each test gets an empty database
on one server per session. The server is HARMONY_TEST_POSTGRES_URL when set (a URL to a
server where the user may create databases), otherwise the contract stack's pinned
Postgres image started on a random loopback port and removed afterwards. Tests skip when
neither is available.

Parametrize `postgres_server` indirectly with an OID to get a server in docker whose
next OID is that value, as on a long-lived cluster whose OID counter has passed 2^31.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import time
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

import psycopg2
import pytest

# Same image as tests/contract/stack/compose.yaml.
IMAGE = (
    "postgres:15.2-alpine"
    "@sha256:d9c304353c031b21e9a7e33dc4781e272a9fa802a2ab9703fe4199d72ba1422c"
)
READY_TIMEOUT_SECONDS = 60


def _wait_until_ready(url: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while True:
        try:
            psycopg2.connect(url, connect_timeout=2).close()
            return
        except psycopg2.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


# Initialises the cluster itself, because the image's entrypoint starts the server
# right after initdb, and pg_resetwal needs it stopped.
RAISED_OID_START = """set -e
printf '%s\\n' "$POSTGRES_PASSWORD" > /tmp/password
initdb --username=postgres --pwfile=/tmp/password --auth=scram-sha-256 >/dev/null
echo 'host all all all scram-sha-256' >> "$PGDATA/pg_hba.conf"
pg_resetwal --next-oid="$NEXT_OID" "$PGDATA"
exec postgres -c listen_addresses='*'
"""


def _start_container(next_oid: int | None = None) -> tuple[str, str]:
    password = secrets.token_hex(16)
    options: list[str] = []
    command = [IMAGE]
    if next_oid is not None:
        options = ["--env", f"NEXT_OID={next_oid}", "--user", "postgres"]
        command = ["--entrypoint", "sh", IMAGE, "-c", RAISED_OID_START]
    container = subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--env",
            f"POSTGRES_PASSWORD={password}",
            "--publish",
            "127.0.0.1::5432",
            *options,
            *command,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    published = subprocess.run(
        ["docker", "port", container, "5432/tcp"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()[0]
    port = published.rsplit(":", 1)[1]
    return container, f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres"


def _check_next_oid(url: str, next_oid: int) -> None:
    with psycopg2.connect(url) as conn, conn.cursor() as cursor:
        cursor.execute("CREATE TEMPORARY TABLE probe ()")
        cursor.execute("SELECT 'probe'::regclass::oid::bigint")
        (oid,) = cursor.fetchone()
    conn.close()
    assert oid >= next_oid, f"the server handed out OID {oid}, below {next_oid}"


@pytest.fixture(name="postgres_server", scope="session")
def fixture_postgres_server(request: pytest.FixtureRequest) -> Iterator[str]:
    next_oid = getattr(request, "param", None)
    configured = os.environ.get("HARMONY_TEST_POSTGRES_URL")
    if configured and next_oid is None:
        yield configured
        return
    if not shutil.which("docker"):
        pytest.skip("needs HARMONY_TEST_POSTGRES_URL or docker")
    try:
        container, url = _start_container(next_oid)
    except subprocess.CalledProcessError as error:
        pytest.skip(f"could not start Postgres in docker: {error.stderr.strip()}")
    try:
        _wait_until_ready(url)
        if next_oid is not None:
            _check_next_oid(url, next_oid)
        yield url
    finally:
        subprocess.run(["docker", "stop", container], capture_output=True, check=False)


@pytest.fixture(name="postgres_database")
def fixture_postgres_database(postgres_server: str) -> Iterator[str]:
    name = f"test_{secrets.token_hex(6)}"
    admin = psycopg2.connect(postgres_server)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE {name}")
        parts = urlsplit(postgres_server)
        yield urlunsplit(parts._replace(path=f"/{name}"))
        with admin.cursor() as cursor:
            cursor.execute(f"DROP DATABASE {name} WITH (FORCE)")
    finally:
        admin.close()
