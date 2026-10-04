import os

import pytest


def pytest_configure(config):
    # WP-2f's marker for tests that need a running stack; registered here too
    # so the contract suite runs cleanly before WP-2f's pytest config lands.
    config.addinivalue_line("markers", "stack: needs a running docker compose stack")


@pytest.fixture(scope="session")
def contract_runner():
    """A runner bound to the server under test, shared by every replayed case
    so that captures flow from one case to the next, as when recording."""
    base_url = os.environ.get("CONTRACT_BASE_URL")
    if not base_url:
        pytest.skip(
            "CONTRACT_BASE_URL is not set; start tests/contract/stack/stack.sh up to replay"
        )
    from .runner import Credentials, Runner

    return Runner(base_url.rstrip("/"), Credentials.from_env())
