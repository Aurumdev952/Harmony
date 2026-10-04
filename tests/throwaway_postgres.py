"""A throwaway Postgres for tests that need real foreign keys, COPY and ON CONFLICT.

Import `postgres_database` into a conftest to use it. Each test gets an empty database
on one server per session. The server is HARMONY_TEST_POSTGRES_URL when set (a URL to a
server where the user may create databases), otherwise the contract stack's pinned
Postgres image started on a random loopback port and removed afterwards. Tests skip when
neither is available.
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


def _start_container() -> tuple[str, str]:
    password = secrets.token_hex(16)
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
            IMAGE,
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


@pytest.fixture(name="postgres_server", scope="session")
def fixture_postgres_server() -> Iterator[str]:
    configured = os.environ.get("HARMONY_TEST_POSTGRES_URL")
    if configured:
        yield configured
        return
    if not shutil.which("docker"):
        pytest.skip("needs HARMONY_TEST_POSTGRES_URL or docker")
    try:
        container, url = _start_container()
    except subprocess.CalledProcessError as error:
        pytest.skip(f"could not start Postgres in docker: {error.stderr.strip()}")
    try:
        _wait_until_ready(url)
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
