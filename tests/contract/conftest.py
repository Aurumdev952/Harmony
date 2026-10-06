import os

import pytest


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
